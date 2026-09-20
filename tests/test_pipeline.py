from datetime import date

import pandas as pd
import pytest

from dengue_link.pipeline import complete_weeks, weekly_division_rain


def test_district_rain_becomes_weekly_division_rain_on_dghs_weeks():
    days = pd.date_range("2026-01-01", periods=14).date
    rain = pd.DataFrame({"d1": [1.0] * 14, "d2": [3.0] * 14, "d3": [10.0] * 14}, index=days)
    out = weekly_division_rain(rain, {"d1": "X", "d2": "X", "d3": "Y"}, [date(2026, 1, 1), date(2026, 1, 8)])
    assert out.loc[date(2026, 1, 1), "X"] == pytest.approx(14.0)
    assert out.loc[date(2026, 1, 8), "Y"] == pytest.approx(70.0)


def test_the_current_unfinished_week_is_dropped():
    weeks = pd.DataFrame({"X": [5.0, 6.0, 2.0]}, index=[date(2026, 9, 3), date(2026, 9, 10), date(2026, 9, 17)])
    assert list(complete_weeks(weeks, today=date(2026, 9, 19)).index) == [date(2026, 9, 3), date(2026, 9, 10)]
    assert len(complete_weeks(weeks, today=date(2026, 9, 24))) == 3


def test_dncc_ward_shapefile_becomes_geojson_with_ward_numbers():
    from pathlib import Path

    from dengue_link.pipeline import ward_geojson

    wards = ward_geojson(Path(__file__).parent.parent / "data" / "raw" / "dncc_wards")
    assert len(wards["features"]) == 54
    assert {f["properties"]["ward"] for f in wards["features"]} == set(range(1, 55))
    assert wards["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_refresh_replaces_a_sources_rows_with_the_fresh_fetch(tmp_path):
    from dengue_link import db
    from dengue_link.pipeline import refresh

    conn = db.connect(tmp_path / "t.db")
    db.put(conn, "src", "m", date(2026, 1, 1), {"old": 1})
    refresh(conn, "src", lambda: db.put(conn, "src", "m", date(2026, 9, 1), {"new": 2}))
    assert conn.execute("select area from obs where source='src'").fetchall() == [("new",)]


def test_failed_fetch_leaves_no_old_values_behind(tmp_path):
    from dengue_link import db
    from dengue_link.pipeline import refresh

    conn = db.connect(tmp_path / "t.db")
    db.put(conn, "src", "m", date(2026, 1, 1), {"old": 1})
    db.put(conn, "other", "m", date(2026, 1, 1), {"keep": 1})

    def boom():
        db.put(conn, "src", "m", date(2026, 9, 1), {"half": 1})
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        refresh(conn, "src", boom)
    assert conn.execute("select count(*) from obs where source='src'").fetchone() == (0,)
    assert conn.execute("select count(*) from obs where source='other'").fetchone() == (1,)


def test_sources_are_fetched_in_parallel_with_rising_progress(tmp_path, monkeypatch):
    import shutil
    import time
    from pathlib import Path

    from dengue_link import bmd, dghs_dashboard, dghs_scrape, dncc_lab, dncc_plans, dncc_sheets, hospitals, ju_dncc, pipeline, weather

    repo = Path(__file__).parent.parent
    (tmp_path / "data").mkdir()
    shutil.copytree(repo / "data" / "raw", tmp_path / "data" / "raw")

    def slow(*a, **k):
        time.sleep(0.3)
        return []

    for mod in (dghs_dashboard, dncc_lab, dncc_plans, weather, ju_dncc, hospitals, dncc_sheets, bmd):
        monkeypatch.setattr(mod, "fetch", slow)
    monkeypatch.setattr(dghs_scrape, "scrape", slow)

    calls = []
    out, *_ = pipeline.run(
        tmp_path, today=date(2026, 9, 19), progress=lambda pct, msg: calls.append((pct, msg, time.monotonic()))
    )
    seen = [pct for pct, _, _ in calls]
    assert out.exists()
    assert seen == sorted(seen) and seen[-1] == 100
    fetched = [t for _, msg, t in calls if msg.startswith("Fetched")]
    started = next(t for _, msg, t in calls if msg.startswith("Fetching"))
    assert len(fetched) == 9
    assert fetched[-1] - started < 1.0


def test_a_hanging_source_is_marked_unavailable_instead_of_blocking_the_build(tmp_path, monkeypatch):
    import shutil
    import time
    from pathlib import Path

    from dengue_link import dghs_dashboard, dghs_scrape, dncc_lab, dncc_plans, ju_dncc, pipeline, weather

    repo = Path(__file__).parent.parent
    (tmp_path / "data").mkdir()
    shutil.copytree(repo / "data" / "raw", tmp_path / "data" / "raw")
    _no_lists(monkeypatch)
    for mod in (dghs_dashboard, dncc_lab, weather, ju_dncc):
        monkeypatch.setattr(mod, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(dncc_plans, "fetch", lambda *a, **k: time.sleep(5))
    monkeypatch.setattr(dghs_scrape, "scrape", lambda *a, **k: 0)
    monkeypatch.setattr(pipeline, "SOURCE_BUDGET_SECONDS", 0.5)

    calls = []
    out, *_ = pipeline.run(tmp_path, today=date(2026, 9, 19), progress=lambda pct, msg: calls.append((msg, time.monotonic())))
    started = next(t for msg, t in calls if msg.startswith("Fetching"))
    assert calls[-1][1] - started < 2
    page = out.read_text()
    assert "Dhaka North: ward spraying plans" in page and "not available right now" in page


def test_season_signal_is_how_cases_usually_change_at_that_time_of_year():
    import numpy as np

    from dengue_link.pipeline import season_signal

    days = pd.date_range("2023-01-01", "2024-12-31")
    k = ((days.dayofyear - 1) // 7).to_numpy()
    national = pd.Series(np.where(k < 30, 70.0, 70.0 * 2.0 ** np.minimum(k - 30, 10)), index=days.date)
    out = season_signal(national, [date(2026, 1, 1), date(2026, 8, 6)])
    assert abs(out.loc[date(2026, 1, 1)]) < 0.05
    assert out.loc[date(2026, 8, 6)] == pytest.approx(np.log(2), abs=0.05)


def test_aedes_signal_only_applies_to_dhaka_and_uses_counts_from_weeks_earlier():
    import numpy as np

    from dengue_link.pipeline import aedes_signal

    weeks = [date(2026, 7, 16) + pd.Timedelta(days=7 * i) for i in range(5)]
    counts = pd.Series({date(2026, 7, 21): 100.0, date(2026, 7, 28): 100.0, date(2026, 8, 4): 300.0}, dtype=float)
    out = aedes_signal(counts, weeks, ["Dhaka", "Sylhet"])
    assert (out["Sylhet"] == 0).all()
    assert out.loc[weeks[4], "Dhaka"] == pytest.approx(np.log(301 / 101), abs=0.01)
    assert out.loc[weeks[2], "Dhaka"] == 0


def test_weekly_weather_signal_is_the_week_mean_from_two_weeks_earlier_standardised():
    from dengue_link.pipeline import weekly_division_mean

    days = pd.date_range("2026-01-01", periods=35).date
    temp = pd.DataFrame({"X": [20.0] * 7 + [30.0] * 7 + [20.0] * 21}, index=days)
    starts = [date(2026, 1, 1) + pd.Timedelta(days=7 * i) for i in range(5)]
    out = weekly_division_mean(temp, starts)
    assert out["X"].isna().sum() == 2
    assert out.loc[starts[3], "X"] == out["X"].max()
    assert abs(out["X"].mean()) < 1e-9


def test_past_season_history_is_kept_when_its_source_is_slow(tmp_path, monkeypatch):
    import shutil
    import time
    from pathlib import Path

    from dengue_link import db, dghs_dashboard, dghs_scrape, dncc_lab, dncc_plans, ju_dncc, pipeline, weather

    repo = Path(__file__).parent.parent
    (tmp_path / "data").mkdir()
    shutil.copytree(repo / "data" / "raw", tmp_path / "data" / "raw")
    conn = db.connect(tmp_path / "data" / "dengue_link.db")
    db.put(conn, "dncc_lab", "dengue_admit_24h", date(2024, 9, 1), {"Bangladesh": 900})
    _no_lists(monkeypatch)
    for mod in (dghs_dashboard, weather, ju_dncc, dncc_plans):
        monkeypatch.setattr(mod, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(dghs_scrape, "scrape", lambda *a, **k: 0)
    monkeypatch.setattr(dncc_lab, "fetch", lambda *a, **k: time.sleep(2))
    monkeypatch.setattr(pipeline, "SOURCE_BUDGET_SECONDS", 0.3)
    pipeline.run(tmp_path, today=date(2026, 9, 19))
    assert conn.execute("select value from obs where source='dncc_lab'").fetchone() == (900.0,)


def _sandbox(tmp_path):
    import shutil
    from pathlib import Path

    (tmp_path / "data").mkdir()
    shutil.copytree(Path(__file__).parent.parent / "data" / "raw", tmp_path / "data" / "raw")
    shutil.copy(Path(__file__).parent.parent / "data" / "pn_kc.npz", tmp_path / "data" / "pn_kc.npz")


def _no_lists(monkeypatch):
    from dengue_link import bmd, dncc_sheets, hospitals

    monkeypatch.setattr(hospitals, "fetch", lambda *a, **k: {"checked": "2026-09-19", "items": []})
    monkeypatch.setattr(dncc_sheets, "fetch", lambda *a, **k: {"centres": {"checked": "2026-09-19", "items": []}, "spray": None, "wards": None})
    monkeypatch.setattr(bmd, "fetch", lambda *a, **k: {"forecast": None, "warnings": []})


def _quiet_sources(monkeypatch, dashboard):
    from dengue_link import dghs_dashboard, dghs_scrape, dncc_lab, dncc_plans, ju_dncc, weather

    _no_lists(monkeypatch)
    for mod in (weather, ju_dncc, dncc_plans, dncc_lab):
        monkeypatch.setattr(mod, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(dghs_scrape, "scrape", lambda *a, **k: 0)
    monkeypatch.setattr(dghs_dashboard, "fetch", dashboard)


def test_early_in_the_year_shows_a_clear_page_instead_of_crashing(tmp_path, monkeypatch):
    from dengue_link import db, pipeline

    _sandbox(tmp_path)

    def five_weeks(conn):
        for i in range(5):
            db.put(conn, "dghs_dashboard", "dengue_admit_week", date(2026, 1, 1) + pd.Timedelta(days=7 * i),
                   {d: 50.0 + i for d in ("Barisal", "Chittagong", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet")})
        return list(range(5))

    _quiet_sources(monkeypatch, five_weeks)
    out, model, _ = pipeline.run(tmp_path, today=date(2026, 2, 20))
    assert model is None
    assert "too early in the year" in out.read_text()


def test_a_source_that_answers_too_late_cannot_write_into_the_build(tmp_path, monkeypatch):
    import time

    from dengue_link import db, pipeline, weather

    _sandbox(tmp_path)
    _quiet_sources(monkeypatch, lambda conn: [])

    def slow_weather(conn, *a, **k):
        db.put(conn, "open_meteo", "rain_mm", date(2026, 9, 1), {"Dhaka": 1.0})
        time.sleep(0.8)
        db.put(conn, "open_meteo", "rain_mm", date(2026, 9, 2), {"Dhaka": 2.0})

    monkeypatch.setattr(weather, "fetch", slow_weather)
    monkeypatch.setattr(pipeline, "SOURCE_BUDGET_SECONDS", 0.3)
    pipeline.run(tmp_path, today=date(2026, 9, 19))
    time.sleep(1.0)
    conn = db.connect(tmp_path / "data" / "dengue_link.db")
    assert conn.execute("select count(*) from obs where source='open_meteo'").fetchone() == (0,)


def test_season_signal_ignores_the_short_last_week_of_the_year():
    import numpy as np

    from dengue_link.pipeline import season_signal

    days = pd.date_range("2022-01-01", "2025-12-31")
    national = pd.Series(100.0, index=days.date)
    out = season_signal(national, [date(2026, 12, 17), date(2026, 12, 24)])
    assert abs(out.loc[date(2026, 12, 17)]) < 0.05
    assert abs(out.loc[date(2026, 12, 24)]) < 0.05


def _dashboard_with(extra):
    from dengue_link import db

    divisions = ("Barisal", "Chittagong", "Dhaka", "Khulna", "Mymensingh", "Rajshahi", "Rangpur", "Sylhet")

    def fetch(conn):
        for i in range(20):
            db.put(conn, "dghs_dashboard", "dengue_admit_week", date(2026, 1, 1) + pd.Timedelta(days=7 * i),
                   {d: 40.0 + 9 * i + 3 * j for j, d in enumerate(divisions)})
        extra(conn)
        return list(range(20))

    return fetch


def test_who_is_getting_sick_and_the_dhaka_city_counts_reach_the_page(tmp_path, monkeypatch):
    import json
    import re

    from dengue_link import db, pipeline

    _sandbox(tmp_path)
    day = date(2026, 5, 25)

    def who(conn):
        for sex, n in (("male", 30), ("female", 20)):
            db.put(conn, "dghs_dashboard", f"dengue_cases_year_{sex}", day, {"0-15": n, "16-30": 2 * n, "31-45": n, "46-60": n, "61+": n})
            db.put(conn, "dghs_dashboard", f"dengue_deaths_year_{sex}", day, {"0-15": 1, "16-30": 1, "31-45": 2, "46-60": 1, "61+": 1})
        db.put(conn, "dghs_dashboard", "dengue_admit_24h_city", day, {"DNCC": 61})
        db.put(conn, "dghs_dashboard", "dengue_admit_year_city", day, {"DNCC": 6826, "DSCC": 7142})

    _quiet_sources(monkeypatch, _dashboard_with(who))
    out, model, _ = pipeline.run(tmp_path, today=day)
    assert model is not None
    page = out.read_text()
    assert 'id="who"' in page and "16 to 30" in page
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert data["city"] == {"DNCC": {"day": 61, "year": 6826}, "DSCC": {"day": 0, "year": 7142}}


def test_the_page_still_builds_when_the_dashboard_gives_no_age_figures(tmp_path, monkeypatch):
    from dengue_link import pipeline

    _sandbox(tmp_path)
    _quiet_sources(monkeypatch, _dashboard_with(lambda conn: None))
    out, model, _ = pipeline.run(tmp_path, today=date(2026, 5, 25))
    assert model is not None
    assert 'id="who"' not in out.read_text()


def test_each_dncc_ward_gets_a_centre_point_for_placing_free_test_centres():
    from pathlib import Path

    from dengue_link.pipeline import ward_centres, ward_geojson

    centres = ward_centres(ward_geojson(Path(__file__).parent.parent / "data" / "raw" / "dncc_wards"))
    assert set(centres) == set(range(1, 55))
    assert all(23.7 < lat < 23.95 and 90.3 < lon < 90.5 for lat, lon in centres.values())


HOSPITAL = {"name": "Sylhet MAG Osmani Medical College Hospital", "bn": "সিলেট এম এ জি ওসমানী মেডিকেল কলেজ হাসপাতাল", "kind": "medical_college",
            "lat": 24.9, "lon": 91.85, "phone": "01700000001", "emergency": True, "ambulance": True, "beds": 900}


def test_hospitals_and_test_centres_reach_the_page(tmp_path, monkeypatch):
    import json
    import re

    from dengue_link import dncc_sheets, hospitals, pipeline

    _sandbox(tmp_path)
    _quiet_sources(monkeypatch, _dashboard_with(lambda conn: None))
    asked = {}

    def centres(cache, today, ward_centres):
        asked.update(cache=cache, wards=len(ward_centres))
        return {"centres": {"checked": "2026-05-25", "items": [{"name": "X", "bn": "এক্স", "kind": "free", "ward": 1, "lat": 23.87, "lon": 90.38, "approx": True}]},
                "spray": {"checked": "2026-05-25", "items": {"9": [{"days": [1, 5], "areas": [["Mirpur 1", "মিরপুর ১"]]}]}},
                "wards": {"date": "2026-05-24", "wards": {"9": {"level": "Moderate", "patients": 40}}}}

    def registry(cache, in_district, today):
        asked["pin_check"] = in_district("Dhaka", 23.7269, 90.3975) and not in_district("Sylhet", 24.0, 92.0)
        return {"checked": "2026-05-24", "items": [HOSPITAL]}

    monkeypatch.setattr(hospitals, "fetch", registry)
    monkeypatch.setattr(dncc_sheets, "fetch", centres)
    out, *_ = pipeline.run(tmp_path, today=date(2026, 5, 25))
    page = out.read_text()
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert data["hospitals"] == [HOSPITAL] and data["testCentres"][0]["name"] == "X"
    assert data["wardRisk"]["wards"]["9"]["level"] == "Moderate" and data["spray"]["9"][0]["days"] == [1, 5]
    assert len(data["history"]["weeks"]) == 12 and len(data["history"]["levels"]["Dhaka"]) == 12
    assert "24 May 2026" in page
    assert asked == {"cache": tmp_path / "data" / "cache", "wards": 54, "pin_check": True}


def test_when_the_registry_is_down_the_list_saved_earlier_is_used(tmp_path, monkeypatch):
    import json
    import re

    from dengue_link import hospitals, pipeline

    _sandbox(tmp_path)
    _quiet_sources(monkeypatch, _dashboard_with(lambda conn: None))
    (tmp_path / "data" / "cache").mkdir()
    (tmp_path / "data" / "cache" / "hospitals.json").write_text(json.dumps({"checked": "2026-05-01", "items": [HOSPITAL]}, ensure_ascii=False))

    def down(cache, in_district, today):
        raise ConnectionError("registry down")

    monkeypatch.setattr(hospitals, "fetch", down)
    out, *_ = pipeline.run(tmp_path, today=date(2026, 5, 25))
    page = out.read_text()
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert data["hospitals"] == [HOSPITAL]
    assert "1 May 2026" in page


def test_todays_official_forecast_and_warnings_reach_the_page(tmp_path, monkeypatch):
    import json
    import re

    from dengue_link import bmd, pipeline

    _sandbox(tmp_path)
    _quiet_sources(monkeypatch, _dashboard_with(lambda conn: None))
    monkeypatch.setattr(bmd, "fetch", lambda conn: {"forecast": {"date": "2026-05-25", "divisions": {"Sylhet": {"coverage": "A FEW PLACES", "heavy": False}}},
                                                    "warnings": []})
    out, *_ = pipeline.run(tmp_path, today=date(2026, 5, 25))
    page = out.read_text()
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1))
    assert data["weather"]["divisions"] == {"Sylhet": {"coverage": "A FEW PLACES", "heavy": False}} and data["warnings"] == []
    assert "Meteorological Department (BMD): today" in page


def test_when_the_met_department_is_down_the_page_simply_has_no_rain_line(tmp_path, monkeypatch):
    import json
    import re

    from dengue_link import bmd, pipeline

    _sandbox(tmp_path)
    _quiet_sources(monkeypatch, _dashboard_with(lambda conn: None))

    def down(conn):
        raise ConnectionError("bmd down")

    monkeypatch.setattr(bmd, "fetch", down)
    out, model, _ = pipeline.run(tmp_path, today=date(2026, 5, 25))
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', out.read_text(), re.S).group(1))
    assert model is not None and data["weather"] is None and data["warnings"] == []


def test_a_saved_list_older_than_two_months_is_not_shown(tmp_path, monkeypatch):
    import json
    import re

    from dengue_link import hospitals, pipeline

    _sandbox(tmp_path)
    _quiet_sources(monkeypatch, _dashboard_with(lambda conn: None))
    (tmp_path / "data" / "cache").mkdir()
    (tmp_path / "data" / "cache" / "hospitals.json").write_text(json.dumps({"checked": "2026-03-01", "items": [HOSPITAL]}, ensure_ascii=False))

    def down(cache, in_district, today):
        raise ConnectionError("registry down")

    monkeypatch.setattr(hospitals, "fetch", down)
    out, *_ = pipeline.run(tmp_path, today=date(2026, 5, 25))
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', out.read_text(), re.S).group(1))
    assert data["hospitals"] is None


def test_the_latest_complete_week_ends_on_a_saturday():
    weeks = pd.DataFrame({"X": [5.0, 6.0]}, index=[date(2026, 9, 6), date(2026, 9, 13)])
    assert len(complete_weeks(weeks, today=date(2026, 9, 19))) == 1
    assert len(complete_weeks(weeks, today=date(2026, 9, 20))) == 2
