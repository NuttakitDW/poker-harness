"""Exact combo-weighted first-in action frequencies by Hwang tier for both seeds of a solve.

Usage: python solver_frequencies.py --stack 20|100  ->  <generated>/solver_frequencies.json
No sampling: each tier-pure bucket's average strategy is weighted by its physical hands.
"""

from __future__ import annotations

import json

import numpy as np

from plo_premium_proof.fullsolve import load_full
from plo_premium_proof.fulltree import FullTree
from plo_premium_proof.tables import FIRST_IN_POSITIONS, HandTables

from study import TIERS, from_args, root_mixes

LABELS = {0: "fold", 2: "limp", 3: "pot_open"}


def tier_rows(mix: np.ndarray, tables: HandTables, weights: np.ndarray, labels: list[str]) -> dict:
    result = {}
    for code, tier in enumerate(TIERS):
        mask = tables.bucket_tier == code
        values = (mix[mask, : len(labels)] * weights[mask, None]).sum(0) / weights[mask].sum()
        result[tier] = dict(zip(labels, map(float, values)))
    everyone = (mix[:, : len(labels)] * weights[:, None]).sum(0) / weights.sum()
    result["All"] = dict(zip(labels, map(float, everyone)))
    return result


def main() -> None:
    study = from_args(__doc__)
    tables = HandTables.build()
    weights = np.bincount(tables.bucket_of, minlength=tables.bucket_count).astype(float)
    tree = FullTree.build(study.tree_config)
    output: dict[str, dict] = {}
    for seed in (1, 2):
        strategy_sum, meta = load_full(study.model(seed))
        mixes, actions = root_mixes(strategy_sum, tree, tables.bucket_count)
        del strategy_sum
        output[f"{study.tag}-seed{seed}"] = {"meta": meta, "seats": {
            name: tier_rows(mixes[s], tables, weights, [LABELS[a] for a in actions[s]])
            for s, name in enumerate(FIRST_IN_POSITIONS)}}
    out = study.generated / "solver_frequencies.json"
    out.write_text(json.dumps(output, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
