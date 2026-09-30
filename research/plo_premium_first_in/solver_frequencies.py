"""Exact combo-weighted first-in action frequencies by Hwang tier for every solve.

Reads the four checkpoints (100bb check-down seeds 1-2, 20bb all-streets seeds 1-2)
and writes generated/solver_frequencies.json. No sampling: each tier-pure bucket's
average strategy is weighted by the number of physical hands in it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from plo_premium_proof.fullsolve import load_full, row_policy
from plo_premium_proof.fulltree import FullTree, FullTreeConfig
from plo_premium_proof.solve import load_model
from plo_premium_proof.tables import FIRST_IN_POSITIONS, HandTables, TreeArrays
from plo_premium_proof.verify import average_policy, root_labels
from plo_thesis_audit.tiers import TIERS

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "tmp" / "plo_premium_proof"
OUT = Path(__file__).resolve().parent / "generated" / "solver_frequencies.json"


def tier_rows(policy_rows: np.ndarray, tables: HandTables, weights: np.ndarray, labels: list[str]):
    result = {}
    for code, tier in enumerate(TIERS):
        mask = tables.bucket_tier == code
        mix = (policy_rows[mask, : len(labels)] * weights[mask, None]).sum(0) / weights[mask].sum()
        result[tier] = dict(zip(labels, map(float, mix)))
    everyone = (policy_rows[:, : len(labels)] * weights[:, None]).sum(0) / weights.sum()
    result["All"] = dict(zip(labels, map(float, everyone)))
    return result


def main() -> None:
    tables = HandTables.build()
    weights = np.bincount(tables.bucket_of, minlength=tables.bucket_count).astype(float)
    output: dict[str, dict] = {}
    checkdown = TreeArrays.build()
    for seed in (1, 2):
        _, strategy_sum, meta = load_model(RUNS / f"seed-{seed}" / "model.npz")
        policy = average_policy(strategy_sum, checkdown)
        output[f"checkdown100-seed{seed}"] = {"meta": meta, "seats": {
            name: tier_rows(policy[int(checkdown.decision_index[checkdown.first_in_nodes[s]])],
                            tables, weights, root_labels(checkdown, s))
            for s, name in enumerate(FIRST_IN_POSITIONS)}}
    full = FullTree.build(FullTreeConfig(stack_bb=20.0))
    labels = {0: "fold", 2: "limp", 3: "pot_open"}
    for seed in (1, 2):
        strategy_sum, meta = load_full(RUNS / f"full20-seed-{seed}" / "model.npz")
        policy = row_policy(strategy_sum, full)
        del strategy_sum
        seats = {}
        for s, name in enumerate(FIRST_IN_POSITIONS):
            node = int(full.first_in_nodes[s])
            start = int(full.row_start[full.decision_index[node]])
            names = [labels[int(a)] for a in full.action_ids[node, : full.action_count[node]]]
            seats[name] = tier_rows(policy[start:start + tables.bucket_count], tables, weights, names)
        output[f"full20-seed{seed}"] = {"meta": meta, "seats": seats}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
