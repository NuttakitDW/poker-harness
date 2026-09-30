"""Every suit-isomorphism class with its features, Hwang tier/form and 20bb first-in mix.

Writes generated/class_actions.json: one row per class (16,432), weighted by physical
combinations, with the seed-averaged fold/limp/open probability at UTG..SB.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from plo_premium_proof.fullsolve import load_full, row_policy
from plo_premium_proof.fulltree import FullTree, FullTreeConfig
from plo_premium_proof.tables import FIRST_IN_POSITIONS, HandTables, colex_index, hand_classes
from plo_premium_proof.verify import hwang_form

from features import features, hand_text, rank_text

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "tmp" / "plo_premium_proof"
OUT = HERE / "generated" / "class_actions.json"


def main() -> None:
    tables = HandTables.build()
    tree = FullTree.build(FullTreeConfig(stack_bb=20.0))
    roots = [int(tree.row_start[tree.decision_index[tree.first_in_nodes[s]]]) for s in range(5)]
    mixes = np.zeros((5, tables.bucket_count, 3))
    for seed in (1, 2):
        strategy_sum, _ = load_full(RUNS / f"full20-seed-{seed}" / "model.npz")
        policy = row_policy(strategy_sum, tree)
        del strategy_sum
        for seat, start in enumerate(roots):
            mixes[seat] += policy[start:start + tables.bucket_count] / 2
        del policy
    rows = []
    for hand in hand_classes(tables):
        bucket = int(tables.bucket_of[colex_index(hand.cards)])
        row = {"hand": hand_text(hand.cards), "ranks": rank_text(hand.cards), "combos": hand.combos,
               "tier": hand.tier, "form": hwang_form(hand), "bucket": bucket, **features(hand.cards)}
        for seat, name in enumerate(FIRST_IN_POSITIONS):
            fold, limp, raise_ = (float(x) for x in mixes[seat, bucket])
            row[name] = {"fold": fold, "limp": limp, "open": raise_}
        rows.append(row)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows))
    print(f"wrote {len(rows)} classes, {sum(r['combos'] for r in rows)} combos -> {OUT}")


if __name__ == "__main__":
    main()
