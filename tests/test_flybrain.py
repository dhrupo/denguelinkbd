from pathlib import Path

import numpy as np
import pytest

from dengue_link.flybrain import FlyCircuit, build_pn_kc

ROOT = Path(__file__).parent.parent
FLYWIRE = ROOT / "data" / "cache" / "flywire"


@pytest.fixture(scope="module")
def circuit():
    return FlyCircuit.load(ROOT / "data" / "pn_kc.npz")


@pytest.mark.skipif(not (FLYWIRE / "connectivity_783.parquet").exists(), reason="FlyWire download not present")
def test_real_wiring_looks_like_a_fly_mushroom_body(tmp_path):
    glomeruli, W = build_pn_kc(FLYWIRE / "annotations.tsv", FLYWIRE / "connectivity_783.parquet", side="right")
    assert 40 <= len(glomeruli) <= 60
    assert 1500 <= W.shape[1] <= 3000
    claws = (W > 0).sum(axis=0)
    assert 3 <= np.median(claws[claws > 0]) <= 10


def test_code_keeps_five_percent_of_kenyon_cells(circuit):
    code = circuit.code(np.random.default_rng(0).normal(size=64))
    assert code.sum() == round(0.05 * circuit.W.shape[1])


def test_similar_district_patterns_share_more_kenyon_cells(circuit):
    rng = np.random.default_rng(1)
    x = rng.normal(size=64)
    near = x + rng.normal(scale=0.1, size=64)
    far = rng.normal(size=64)
    overlap = lambda a, b: (circuit.code(a) & circuit.code(b)).sum()
    assert overlap(x, near) > overlap(x, far)


def test_novelty_is_low_for_a_familiar_pattern_and_high_for_a_new_one(circuit):
    rng = np.random.default_rng(2)
    usual = rng.normal(size=64)
    memory = [circuit.code(usual + rng.normal(scale=0.05, size=64)) for _ in range(20)]
    assert circuit.novelty(usual, memory) < 0.3
    assert circuit.novelty(rng.normal(size=64), memory) > 0.6


def test_an_out_of_pattern_week_scores_higher_novelty_than_ordinary_weeks(circuit):
    import pandas as pd

    from dengue_link.flybrain import novelty_series

    rng = np.random.default_rng(3)
    weeks = pd.DataFrame(rng.poisson(200, size=(30, 8)).astype(float), columns=list("ABCDEFGH"))
    weeks.loc[25, ["C", "F"]] *= 4
    scores = novelty_series(circuit, weeks)
    assert scores.idxmax() == 25
    assert scores[25] > scores.drop(25).median() + 0.2
