import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import shapefile

from dengue_link import bmd, db, dghs_dashboard, dghs_scrape, dncc_lab, dncc_plans, dncc_sheets, hospitals, ju_dncc, weather
from dengue_link.areas import build_areas, pin_checker
from dengue_link.flybrain import FlyCircuit, novelty_series
from dengue_link.forecast import backtest, fit, forecast, split_by_share
from dengue_link.mapview import render, render_unavailable


def refresh(conn, source, fetch):
    db.clear(conn, source)
    try:
        return fetch()
    except Exception:
        db.clear(conn, source)
        raise


def season_signal(national_daily, week_starts):
    days = pd.to_datetime(pd.Index(national_daily.index))
    daily = pd.Series(national_daily.to_numpy(dtype=float), index=days)
    week = (days.dayofyear - 1) // 7
    # Week 52 holds only the last 1-2 days of the year; counting it as a week would fake a drop every December.
    weekly = daily[week < 52].groupby([days.year[week < 52], week[week < 52]]).sum()
    growth = np.log((weekly.groupby(level=0).shift(-1) + 1) / (weekly + 1)).dropna()
    # Averaging each week with its neighbours smooths out noise from only a few past seasons; 3 weeks tested best (82.7 vs 86.4 unsmoothed).
    typical = growth.groupby(level=1).mean().rolling(3, center=True, min_periods=1).mean()
    return pd.Series({w: float(typical.get((w.timetuple().tm_yday - 1) // 7, 0.0)) for w in week_starts})


def aedes_signal(counts, week_starts, divisions):
    starts = pd.to_datetime(pd.Index(week_starts))
    by_week = pd.Series(0.0, index=starts)
    seen = pd.Series(False, index=starts)
    for end, n in counts.items():
        pos = starts.searchsorted(pd.Timestamp(end), side="right") - 1
        if pos >= 0:
            by_week.iloc[pos] += n
            seen.iloc[pos] = True
    lag2, lag3 = by_week.shift(2), by_week.shift(3)
    known = seen.shift(2, fill_value=False) & seen.shift(3, fill_value=False)
    signal = np.log((lag2 + 1) / (lag3 + 1)).where(known, 0.0).fillna(0.0)
    out = pd.DataFrame(0.0, index=list(week_starts), columns=divisions)
    out["Dhaka"] = signal.to_numpy() if "Dhaka" in divisions else 0.0
    return out


def weekly_division_mean(daily, week_starts, lag_weeks=2):
    frame = daily.copy()
    frame.index = pd.to_datetime(frame.index)
    weekly = pd.DataFrame({s: frame.loc[pd.Timestamp(s): pd.Timestamp(s) + pd.Timedelta(days=6)].mean() for s in week_starts}).T
    shifted = weekly.shift(lag_weeks)
    return (shifted - shifted.mean()) / shifted.std().replace(0, 1)


def weekly_division_rain(rain, district_division, week_starts):
    by_division = rain.T.groupby(pd.Series(district_division)).mean().T
    by_division.index = pd.to_datetime(by_division.index)
    return pd.DataFrame(
        {s: by_division.loc[pd.Timestamp(s) : pd.Timestamp(s) + pd.Timedelta(days=6)].sum() for s in week_starts}
    ).T


def complete_weeks(weeks, today):
    return weeks[[start + timedelta(days=6) < today for start in weeks.index]]


def ward_geojson(shp_path):
    r = shapefile.Reader(str(shp_path))
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"ward": int(rec["Ward_no"]), "zone": int(rec["Zone_no"])}, "geometry": shp.__geo_interface__}
            for shp, rec in zip(r.shapes(), r.records())
        ],
    }


def ward_centres(wards):
    centres = {}
    for f in wards["features"]:
        g = f["geometry"]
        ring = max((poly[0] for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]])), key=len)
        centres[f["properties"]["ward"]] = (sum(c[1] for c in ring) / len(ring), sum(c[0] for c in ring) / len(ring))
    return centres


def _saved(path, today):
    # A list saved earlier stands in when its source is down, but not for ever: after two months it is dropped rather than shown as current.
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return saved if saved and (today - date.fromisoformat(saved["checked"])).days <= 60 else None


def _series(conn, source, metric):
    df = pd.read_sql("select date, area, value from obs where source=? and metric=?", conn, params=(source, metric))
    if df.empty:
        return pd.DataFrame()
    out = df.pivot(index="date", columns="area", values="value")
    out.index = [date.fromisoformat(d) for d in out.index]
    return out.sort_index()


# A stalled government server must not hold the page hostage; normal runs finish in about 20 s.
# The unattended daily build has nobody waiting, so it may set a longer wait and lose fewer sources.
SOURCE_BUDGET_SECONDS = int(os.environ.get("DENGUE_LINK_SOURCE_BUDGET", 30))


HOSPITALS, DNCC_SHEETS, BMD = "DGHS hospital list", "DNCC dengue dashboard", "BMD forecast and warnings"


def _sources(areas, today, cache, centres, in_district):
    # (label, source key to refresh or None, fetch(conn), describe(result)).
    # None keeps dated history: past DGHS reports vanish from their list, and past seasons (DNCC Lab) can't go stale.
    return [
        ("DGHS dashboard, weekly cases by division", "dghs_dashboard", dghs_dashboard.fetch, lambda w: f"{len(w)} weeks"),
        ("DGHS daily press-release PDF, cases by district", None, dghs_scrape.scrape, lambda n: f"{n} reports read"),
        ("DNCC Innovation Lab, daily city-corporation history", None, lambda c: dncc_lab.fetch(c, today), lambda _: "2022 onwards"),
        ("DNCC mosquito-control plans", "dncc", dncc_plans.fetch, lambda n: f"{n} plan PDFs read"),
        ("JU–DNCC weekly mosquito surveillance", None, ju_dncc.fetch, lambda n: f"{n} new weekly reports"),
        ("Open-Meteo weather", "open_meteo",
         lambda c: weather.fetch(c, areas.division_centroid, date(today.year, 1, 1), today - timedelta(days=6)),
         lambda _: "daily rain per division"),
        (HOSPITALS, None, lambda c: hospitals.fetch(cache, in_district, today), lambda d: f"{len(d['items'])} hospitals"),
        (DNCC_SHEETS, None, lambda c: dncc_sheets.fetch(cache, today, centres), lambda d: ", ".join(k for k, v in d.items() if v)),
        (BMD, None, bmd.fetch, lambda d: f"{len(d['warnings'])} warnings in force"),
    ]


def _copy_in(conn, rows):
    if rows:
        with conn:
            conn.executemany("insert or replace into obs values (?, ?, ?, ?, ?)", rows)


def _fetch_one(db_path, label, source, fetch, describe):
    # Sources that are replaced each run write into a private in-memory copy, so a late answer can't touch the build.
    conn = db.connect(":memory:" if source else db_path)
    try:
        result = fetch(conn)
        rows = conn.execute("select * from obs").fetchall() if source else None
        return (label, "fetched now", describe(result)), rows, result
    except Exception as e:
        print(f"FAILED {label}: {e}", file=sys.stderr)
        return (label, "unavailable right now", str(e)[:160]), None, None
    finally:
        conn.close()


def run(root=Path("."), today=None, progress=lambda pct, msg: None):
    today = today or date.today()
    raw = root / "data" / "raw"
    progress(2, "Loading map boundaries")
    areas = build_areas(raw / "districts.geojson", raw / "upazilas.geojson", raw / "divisions.geojson")
    db_path = root / "data" / "dengue_link.db"
    db.connect(db_path).close()

    cache = root / "data" / "cache"
    wards = ward_geojson(raw / "dncc_wards")
    specs = _sources(areas, today, cache, ward_centres(wards), pin_checker(raw / "districts.geojson"))
    progress(10, "Fetching " + ", ".join(label for label, *_ in specs))
    done, staged, results = {}, {}, {}
    pool = ThreadPoolExecutor(len(specs))
    futures = {pool.submit(_fetch_one, db_path, *spec): spec[0] for spec in specs}
    try:
        for i, fut in enumerate(as_completed(futures, timeout=SOURCE_BUDGET_SECONDS), 1):
            done[futures[fut]], staged[futures[fut]], results[futures[fut]] = fut.result()
            pending = [label for label, *_ in specs if label not in done]
            progress(10 + 75 * i // len(specs), f"Fetched {futures[fut]}" + (f" — waiting for {', '.join(pending)}" if pending else ""))
    except TimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    conn = db.connect(db_path)
    for label, source, *_ in specs:
        if label not in done:
            print(f"FAILED {label}: no answer within {SOURCE_BUDGET_SECONDS}s", file=sys.stderr)
            done[label] = (label, "unavailable right now", f"no answer within {SOURCE_BUDGET_SECONDS} seconds")
        if source:
            rows = staged.get(label)
            refresh(conn, source, lambda: _copy_in(conn, rows))
    sources = [done[label] for label, *_ in specs]
    progress(88, "Forecasting")

    adults, larvae = _series(conn, "ju_dncc", "aedes_adults"), _series(conn, "ju_dncc", "aedes_larvae")
    mosquito = {"weeks": [
        {"end": d.isoformat(),
         "adults": {int(a[-1]): int(v) for a, v in adults.loc[d].dropna().items()},
         "larvae": {int(a[-1]): int(v) for a, v in larvae.loc[d].dropna().items()} if d in larvae.index else {}}
        for d in adults.index[-12:]
    ]} if not adults.empty else None

    out = root / "out" / "map.html"
    out.parent.mkdir(exist_ok=True)
    weeks = _series(conn, "dghs_dashboard", "dengue_admit_week")
    if weeks.empty:
        render_unavailable(out, as_of=today, sources=sources, reason="dghs_down")
        progress(100, "Done")
        return out, None, None
    weeks = complete_weeks(weeks, today)
    rain = weekly_division_rain(_series(conn, "open_meteo", "rain_mm"), {d: d for d in areas.division_centroid}, weeks.index)
    weeks.index = rain.index = pd.to_datetime(weeks.index)
    starts = list(weeks.index.date)
    national = _series(conn, "dncc_lab", "dengue_admit_24h")
    aedes = _series(conn, "ju_dncc", "aedes_adults")
    extra = {
        "season": pd.DataFrame({d: season_signal(national["Bangladesh"].dropna(), starts) for d in weeks.columns}) if not national.empty else None,
        "aedes": aedes_signal(aedes.sum(axis=1), starts, list(weeks.columns)) if not aedes.empty else None,
        "temp": weekly_division_mean(_series(conn, "open_meteo", "temp_c"), starts),
        "humidity": weekly_division_mean(_series(conn, "open_meteo", "humidity_pct"), starts),
    }
    extra = {k: v.set_axis(weeks.index) for k, v in extra.items() if v is not None and not v.empty}
    nb = areas.division_neighbours
    try:
        model = fit(weeks, rain, nb, period=1, extra=extra)
        divisions = forecast(model, weeks, rain, nb, period=1, extra=extra)
        accuracy = backtest(weeks, rain, nb, start=weeks.index[min(12, len(weeks) - 2)], period=1, extra=extra)
    except ValueError:
        render_unavailable(out, as_of=today, sources=sources, reason="too_early")
        progress(100, "Done")
        return out, None, None

    daily = _series(conn, "dghs", "dengue_admit_24h")
    recent = daily[daily.index > today - timedelta(days=15)].sum().to_dict() if not daily.empty else {}
    districts = split_by_share(divisions, recent, areas.district_division)
    districts["population"] = pd.read_csv(raw / "population_2022.csv", index_col="district")["population_2022"].reindex(districts.index)
    in_hospital, deaths = _series(conn, "dghs", "dengue_in_hospital"), _series(conn, "dghs", "dengue_deaths_year")
    districts["in_hospital"] = in_hospital.iloc[-1].reindex(districts.index) if not in_hospital.empty else np.nan
    districts["deaths_year"] = deaths.iloc[-1].reindex(districts.index) if not deaths.empty else np.nan
    deaths_24h = _series(conn, "dghs", "dengue_deaths_24h")
    national = {"date": in_hospital.index[-1].isoformat(), "in_hospital": in_hospital.iloc[-1].sum(),
                "deaths_year": deaths.iloc[-1].sum(), "deaths_24h": deaths_24h.iloc[-1].sum()} if not in_hospital.empty and not deaths_24h.empty else None

    def latest(metric):
        s = _series(conn, "dghs_dashboard", metric)
        return s.iloc[-1].dropna().to_dict() if not s.empty else {}

    by_sex = {kind: {sex: latest(f"dengue_{kind}_year_{sex}") for sex in ("male", "female")} for kind in ("cases", "deaths")}
    who = {name: {band: {sex: by_sex[kind][sex].get(band, 0) for sex in ("male", "female")} for band in by_sex[kind]["male"]}
           for name, kind in (("patients", "cases"), ("deaths", "deaths"))} if by_sex["cases"]["male"] else None
    # The dashboard's last-day chart leaves out any area with no new patients, so a missing name means zero.
    day, year = latest("dengue_admit_24h_city"), latest("dengue_admit_year_city")
    city = {name: {"day": day.get(name, 0), "year": n} for name, n in year.items()} or None

    sheets, official = results.get(DNCC_SHEETS) or {}, results.get(BMD) or {}
    scores = novelty_series(FlyCircuit.load(root / "data" / "pn_kc.npz"), weeks)
    spray = _series(conn, "dncc", "spray_days_per_week")
    ward_spray = {int(a[6:]): int(v) for a, v in spray.ffill().iloc[-1].dropna().items()} if not spray.empty else {}

    render(
        out,
        upazilas=json.loads((raw / "upazilas.geojson").read_text()),
        upazila_district=areas.upazila_district,
        districts=districts,
        divisions=divisions,
        novelty={"week": scores.index[-1].date(), "score": float(scores.iloc[-1]),
                 "history": [(i.date().isoformat(), float(v)) for i, v in scores.tail(12).items()]} if len(scores) else None,
        backtest=accuracy,
        wards=wards,
        hospitals=results.get(HOSPITALS) or _saved(cache / "hospitals.json", today),
        test_centres=sheets.get("centres") or _saved(cache / "dncc_test_centres.json", today),
        spray=sheets.get("spray") or _saved(cache / "dncc_spray.json", today),
        ward_risk=sheets.get("wards"),
        weather=official.get("forecast"),
        warnings=official.get("warnings") or [],
        past_weeks=weeks.tail(12),
        country=json.loads((raw / "country.geojson").read_text()),
        district_shapes=json.loads((raw / "districts.geojson").read_text()),
        bn=json.loads((raw / "bangla_names.json").read_text(encoding="utf-8")),
        mosquito=mosquito,
        national=national,
        who=who,
        city=city,
        ward_spray=ward_spray,
        as_of=today,
        sources=sources,
    )
    progress(100, "Done")
    return out, model, accuracy
