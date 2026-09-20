from dataclasses import dataclass

import numpy as np
import pandas as pd

from dengue_link.forecast import _beyond_noise

ACTIVE_FRACTION = 0.05
# Background PN firing: without it the top-k code ignores magnitude, so a 1% wobble codes like a 4x outbreak.
# 0.1 gave the widest gap between a 4x rise (novelty >= 0.74) and Poisson-noise weeks (<= 0.38) over 10 seeds.
SPONTANEOUS_PN = 0.1


def build_pn_kc(annotations_path, connectivity_path, side="right"):
    ann = pd.read_csv(
        annotations_path, sep="\t", usecols=["root_id", "cell_class", "cell_type", "side"],
        dtype={"root_id": "int64"}, low_memory=False,
    )
    ann = ann[ann["side"] == side]
    pns = ann[(ann["cell_class"] == "ALPN") & ~ann["cell_type"].fillna("M_").str.startswith("M_")]
    glomerulus = pns.set_index("root_id")["cell_type"].str.split("_").str[0]
    glomerulus = glomerulus[glomerulus.str.fullmatch(r"[DV][A-Z]?\d*[a-z]*")]
    kcs = ann.loc[ann["cell_class"] == "Kenyon_Cell", "root_id"]

    edges = pd.read_parquet(connectivity_path, columns=["Presynaptic_ID", "Postsynaptic_ID", "Connectivity"])
    edges = edges[edges["Presynaptic_ID"].isin(glomerulus.index) & edges["Postsynaptic_ID"].isin(kcs)]
    edges = edges.assign(glomerulus=edges["Presynaptic_ID"].map(glomerulus))
    W = edges.pivot_table(index="glomerulus", columns="Postsynaptic_ID", values="Connectivity", aggfunc="sum", fill_value=0)
    return list(W.index), W.to_numpy(dtype=np.float32)


@dataclass
class FlyCircuit:
    glomeruli: list
    W: np.ndarray

    @classmethod
    def load(cls, path):
        z = np.load(path, allow_pickle=False)
        return cls(list(z["glomeruli"]), z["W"])

    def save(self, path):
        np.savez_compressed(path, glomeruli=np.array(self.glomeruli), W=self.W)

    def _drive(self, x):
        g = len(self.glomeruli)
        pn = SPONTANEOUS_PN + np.bincount(np.arange(len(x)) % g, weights=np.asarray(x, dtype=float), minlength=g)
        return pn @ self.W

    def code(self, x):
        drive = self._drive(x)
        k = round(ACTIVE_FRACTION * len(drive))
        active = np.zeros(len(drive), dtype=bool)
        active[np.argpartition(drive, -k)[-k:]] = True
        return active

    def novelty(self, x, memory):
        c = self.code(x)
        return 1 - max((c & m).sum() for m in memory) / c.sum()


def novelty_series(circuit, periods):
    rises = _beyond_noise(periods, periods.shift(1)).clip(lower=0).iloc[1:]
    memory, scores = [], {}
    for idx, row in rises.iterrows():
        if memory:
            scores[idx] = circuit.novelty(row.to_numpy(), memory)
        memory.append(circuit.code(row.to_numpy()))
    return pd.Series(scores, dtype=float)
