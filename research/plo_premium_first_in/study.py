"""Per-stack-depth settings shared by the study scripts (20bb and 100bb)."""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "tmp" / "plo_premium_proof"
TIERS = ("Premium", "Speculative", "Marginal", "Trash")


@dataclasses.dataclass(frozen=True)
class Study:
    stack: int
    raise_caps: tuple[int, int, int, int]
    generated: Path
    ante: float = 0.0
    tag: str = ""

    def __post_init__(self) -> None:
        if not self.tag:
            object.__setattr__(self, "tag", f"full{self.stack}")

    @property
    def tree_config(self):
        from plo_premium_proof.fulltree import FullTreeConfig
        return FullTreeConfig(stack_bb=float(self.stack), raise_caps=self.raise_caps, ante_bb=self.ante)

    def model(self, seed: int) -> Path:
        return RUNS / f"{self.tag}-seed-{seed}" / "model.npz"

    def premium_report(self, seed: int) -> Path:
        return RUNS / f"{self.tag}-report-seed-{seed}.json"

    def tier_report(self, tier: str) -> Path:
        return self.premium_report(1) if tier == "Premium" else RUNS / "tiers" / f"{self.tag}-{tier}.json"


STUDIES = {
    20: Study(20, (3, 2, 2, 2), HERE / "generated"),
    100: Study(100, (4, 2, 2, 2), HERE / "generated" / "100bb"),
    # MTT: 40bb, 0.116bb ante from every player (not counted in preflop pot-limit size)
    40: Study(40, (4, 2, 2, 2), HERE / "generated" / "mtt40", ante=0.116, tag="mtt40"),
}


def from_args(description: str) -> Study:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--stack", type=int, choices=sorted(STUDIES), default=20)
    study = STUDIES[parser.parse_args().stack]
    study.generated.mkdir(parents=True, exist_ok=True)
    return study


def root_mixes(strategy_sum: np.ndarray, tree, bucket_count: int) -> tuple[np.ndarray, list[list[int]]]:
    """Normalized first-in mixes, shape (5 seats, buckets, 3), plus each seat's action ids.

    Reads only the five first-in rows blocks, so it works for trees whose full
    strategy table would not fit in memory as float64.
    """
    mixes = np.zeros((5, bucket_count, 3))
    actions = []
    for seat in range(5):
        node = int(tree.first_in_nodes[seat])
        count = int(tree.action_count[node])
        start = int(tree.row_start[tree.decision_index[node]])
        block = np.asarray(strategy_sum[start:start + bucket_count, :count], dtype=np.float64)
        totals = block.sum(axis=1, keepdims=True)
        mixes[seat, :, :count] = np.where(totals > 0, block / np.where(totals > 0, totals, 1), 1.0 / count)
        actions.append([int(a) for a in tree.action_ids[node, :count]])
    return mixes, actions
