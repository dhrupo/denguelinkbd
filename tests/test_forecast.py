import numpy as np
import pandas as pd
import pytest

from dengue_link.forecast import backtest, fit, forecast

CHAIN = ["A", "B", "C", "D", "E"]
NEIGHBOURS = {
    d: ({CHAIN[i - 1]} if i > 0 else set()) | ({CHAIN[i + 1]} if i < 4 else set()) for i, d in enumerate(CHAIN)
}


def wave(days=200, lag=21, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(days)
    idx = pd.date_range("2026-03-01", periods=days)
    cases = {d: 2 + 40 / (1 + np.exp(-(t - 40 - i * lag) / 6)) for i, d in enumerate(CHAIN)}
    cases = pd.DataFrame({d: rng.poisson(v) for d, v in cases.items()}, index=idx).astype(float)
    rain = pd.DataFrame(rng.gamma(2, 5, size=(days, len(CHAIN))), index=idx, columns=CHAIN)
    return cases, rain


def test_district_next_to_a_surge_is_predicted_to_rise_before_it_does():
    cases, rain = wave()
    today = cases.index[40 + 21 + 5]
    model = fit(cases.loc[:today], rain.loc[:today], NEIGHBOURS)
    out = forecast(model, cases.loc[:today], rain.loc[:today], NEIGHBOURS)
    assert out.loc["C", "change"] > out.loc["E", "change"]
    assert out.loc["C", "next7"] > cases["C"].loc[:today].tail(7).sum()


def test_forecasts_are_never_negative():
    cases, rain = wave()
    model = fit(cases, rain, NEIGHBOURS)
    assert (forecast(model, cases, rain, NEIGHBOURS)["next7"] >= 0).all()


def test_backtest_reports_model_against_same_as_last_week():
    cases, rain = wave()
    result = backtest(cases, rain, NEIGHBOURS, start=cases.index[90])
    assert {"model_mae", "baseline_mae", "n"} <= set(result)
    assert result["n"] > 50
    assert result["model_mae"] < result["baseline_mae"]


def test_backtest_returns_error_band_and_how_often_it_held():
    cases, rain = wave(days=400)
    result = backtest(cases, rain, NEIGHBOURS, start=cases.index[90])
    low, high = result["band"]
    assert low < 0 < high
    # The band is the middle 80% of past misses; scored only on weeks it hadn't seen, it should hold roughly that often.
    assert 0.65 <= result["band_held"] <= 0.95
    assert 0 < result["band_checked"] < result["n"]


def test_too_little_history_is_refused():
    cases, rain = wave(days=30)
    with pytest.raises(ValueError, match="history"):
        fit(cases, rain, NEIGHBOURS)


def test_weekly_series_use_one_row_per_period():
    cases, rain = wave(days=210)
    weekly_cases, weekly_rain = cases.resample("7D").sum(), rain.resample("7D").sum()
    today = weekly_cases.index[9]
    model = fit(weekly_cases.loc[:today], weekly_rain.loc[:today], NEIGHBOURS, period=1)
    out = forecast(model, weekly_cases.loc[:today], weekly_rain.loc[:today], NEIGHBOURS, period=1)
    assert out.loc["C", "change"] > out.loc["E", "change"]
    assert out.loc["C", "next7"] > weekly_cases.loc[today, "C"]


def test_division_forecast_is_split_across_its_districts_by_recent_share():
    from dengue_link.forecast import split_by_share

    divisions = pd.DataFrame({"recent": [100.0, 10.0], "next7": [150.0, 5.0], "change": [0.5, -0.5]}, index=["X", "Y"])
    district_division = {"x1": "X", "x2": "X", "x3": "X", "y1": "Y"}
    out = split_by_share(divisions, {"x1": 30, "x2": 10, "x3": 0, "y1": 4}, district_division)
    assert out.loc[["x1", "x2", "x3"], "next7"].sum() == pytest.approx(150)
    assert out.loc["y1", "next7"] == pytest.approx(5)
    assert out.loc["x1", "next7"] > out.loc["x2", "next7"] > out.loc["x3", "next7"] > 0
    assert (out.loc[["x1", "x2", "x3"], "change"] == 0.5).all()
    assert out.loc["x1", "division"] == "X"


def test_an_extra_signal_that_explains_growth_is_used_and_helps():
    rng = np.random.default_rng(5)
    idx = pd.date_range("2026-01-01", periods=40, freq="7D")
    growth = pd.DataFrame(rng.normal(0, 0.3, size=(40, len(CHAIN))), index=idx, columns=CHAIN)
    level = 200 * np.exp(growth.cumsum())
    cases = pd.DataFrame(rng.poisson(level), index=idx, columns=CHAIN).astype(float)
    rain = pd.DataFrame(0.0, index=idx, columns=CHAIN)
    hint = growth.shift(-1).fillna(0)
    model = fit(cases, rain, NEIGHBOURS, period=1, extra={"hint": hint})
    assert model["hint"] > 0.5
    with_hint = backtest(cases, rain, NEIGHBOURS, start=idx[15], period=1, extra={"hint": hint})
    without = backtest(cases, rain, NEIGHBOURS, start=idx[15], period=1)
    assert with_hint["model_mae"] < without["model_mae"]


def test_without_extra_signals_the_forecast_is_unchanged():
    cases, rain = wave()
    model = fit(cases, rain, NEIGHBOURS)
    assert set(model) == {"own_growth", "neighbour_growth", "neighbour_pressure", "rain_2_3wk"}


def test_a_forecast_several_weeks_ahead_is_scored_against_the_same_as_this_week_guess():
    # Dengue rises and falls over months, so the test season is a slow wave reaching each district two weeks after the last.
    rng = np.random.default_rng(0)
    t, idx = np.arange(90), pd.date_range("2025-01-05", periods=90, freq="7D")
    cases = pd.DataFrame({d: rng.poisson(60 + 300 * (1 + np.sin(2 * np.pi * (t - 2 * i) / 30))) for i, d in enumerate(CHAIN)},
                         index=idx).astype(float)
    rain = pd.DataFrame(0.0, index=idx, columns=CHAIN)
    one = backtest(cases, rain, NEIGHBOURS, start=idx[30], period=1)
    three = backtest(cases, rain, NEIGHBOURS, start=idx[30], period=1, horizon=3)
    # Guessing "same as this week" gets worse the further ahead it looks; the model should still beat it.
    assert three["baseline_mae"] > one["baseline_mae"]
    assert three["model_mae"] < three["baseline_mae"]
    assert three["n"] == one["n"] - 2 * len(CHAIN)


def test_a_backtest_with_no_past_week_to_score_says_so_instead_of_crashing():
    idx = pd.date_range("2026-01-04", periods=14, freq="7D")
    cases = pd.DataFrame(np.random.default_rng(0).poisson(100, size=(14, len(CHAIN))), index=idx, columns=CHAIN).astype(float)
    with pytest.raises(ValueError, match="history"):
        backtest(cases, cases * 0, NEIGHBOURS, start=idx[12], period=1, horizon=2)
