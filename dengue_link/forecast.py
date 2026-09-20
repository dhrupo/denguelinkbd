from itertools import product

import numpy as np
import pandas as pd

MIN_TRAINING_WEEKS = 4
FEATURES = ["own_growth", "neighbour_growth", "neighbour_pressure", "rain_2_3wk"]


def _beyond_noise(a, b):
    """log(a/b) minus 2 Poisson standard errors, so week-to-week noise in flat districts reads as zero."""
    g = np.log((a + 1) / (b + 1))
    se = np.sqrt(1 / (a + 1) + 1 / (b + 1))
    return np.sign(g) * (g.abs() - 2 * se).clip(lower=0)


def _features(cases, rain, neighbours, period, extra=None):
    week = cases.rolling(period).sum()
    prev = week.shift(period)
    nb_week = pd.DataFrame({d: week[sorted(neighbours[d])].mean(axis=1) for d in cases}, index=cases.index)
    nb_prev = nb_week.shift(period)
    rain_week = rain.reindex(index=cases.index, columns=cases.columns).rolling(period).sum().shift(2 * period)
    rain_z = (rain_week - rain_week.mean()) / rain_week.std().replace(0, 1)
    frames = {
        "recent": week,
        "own_growth": _beyond_noise(week, prev),
        "neighbour_growth": _beyond_noise(nb_week, nb_prev),
        "neighbour_pressure": _beyond_noise(nb_week, week),
        "rain_2_3wk": rain_z.fillna(0),
        "target": np.log((week.shift(-period) + 1) / (week + 1)),
    }
    for name, frame in (extra or {}).items():
        frames[name] = frame.reindex(index=cases.index, columns=cases.columns).fillna(0)
    return pd.concat({k: v.stack() for k, v in frames.items()}, axis=1)


def _design(df, names):
    return np.column_stack([df[f].to_numpy() for f in names])


def fit(cases, rain, neighbours, period=7, extra=None):
    names = FEATURES + list(extra or {})
    rows = _features(cases, rain, neighbours, period, extra).dropna()
    if rows.index.get_level_values(0).nunique() < MIN_TRAINING_WEEKS * period:
        raise ValueError(f"need {MIN_TRAINING_WEEKS}+ weeks of usable history to fit")
    w = np.sqrt(rows["recent"].to_numpy() + 1)
    X, y = _design(rows, names) * w[:, None], rows["target"].to_numpy() * w
    best, best_sse = np.zeros(len(names)), float(y @ y)
    for subset in product([False, True], repeat=len(names)):
        cols = np.flatnonzero(subset)
        if not len(cols):
            continue
        coef, *_ = np.linalg.lstsq(X[:, cols], y, rcond=None)
        sse = float(((X[:, cols] @ coef - y) ** 2).sum())
        if (coef >= 0).all() and sse < best_sse:
            best, best_sse = np.zeros(len(names)), sse
            best[cols] = coef
    return dict(zip(names, best))


def forecast(model, cases, rain, neighbours, period=7, extra=None):
    names = list(model)
    today = _features(cases, rain, neighbours, period, extra).loc[cases.index[-1]].dropna(subset=["recent"] + names)
    log_ratio = _design(today, names) @ np.array(list(model.values()))
    next7 = np.clip((today["recent"] + 1) * np.exp(log_ratio) - 1, 0, None)
    return pd.DataFrame(
        {"recent": today["recent"], "next7": next7, "change": (next7 - today["recent"]) / (today["recent"] + 1)}
    )


def backtest(cases, rain, neighbours, start, period=7, extra=None):
    model_err, base_err = [], []
    for pos in range(cases.index.get_indexer([start], method="bfill")[0], len(cases) - period, period):
        past, past_rain = cases.iloc[: pos + 1], rain.loc[: cases.index[pos]]
        past_extra = {k: v.loc[: cases.index[pos]] for k, v in (extra or {}).items()}
        model = fit(past, past_rain, neighbours, period, past_extra)
        out = forecast(model, past, past_rain, neighbours, period, past_extra)
        actual = cases.iloc[pos + 1 : pos + 1 + period].sum()[out.index]
        model_err += list((out["next7"] - actual).abs())
        base_err += list((out["recent"] - actual).abs())
    return {"model_mae": float(np.mean(model_err)), "baseline_mae": float(np.mean(base_err)), "n": len(model_err)}


def split_by_share(division_out, district_recent, district_division):
    d = pd.DataFrame({"division": pd.Series(district_division)})
    d["recent_cases"] = pd.Series(district_recent).reindex(d.index).fillna(0)
    group = d.groupby("division")["recent_cases"]
    d["share"] = (d["recent_cases"] + 1) / (group.transform("sum") + group.transform("size"))
    d["next7"] = d["share"] * d["division"].map(division_out["next7"])
    d["change"] = d["division"].map(division_out["change"])
    return d
