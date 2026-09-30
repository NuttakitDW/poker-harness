"""Every suit-isomorphism class with its features, Hwang tier/form and first-in mix.

Usage: python class_actions.py --stack 20|100  ->  <generated>/class_actions.json, one row per
class (16,432) weighted by physical combinations, with the seed-averaged fold/limp/open
probability at UTG..SB.
"""

from __future__ import annotations

import json

import numpy as np

from plo_premium_proof.fullsolve import load_full
from plo_premium_proof.fulltree import FullTree
from plo_premium_proof.tables import FIRST_IN_POSITIONS, HandTables, colex_index, hand_classes
from plo_premium_proof.verify import hwang_form

from features import features, hand_text, rank_text
from study import from_args, root_mixes


def main() -> None:
    study = from_args(__doc__)
    tables = HandTables.build()
    tree = FullTree.build(study.tree_config)
    mixes = np.zeros((5, tables.bucket_count, 3))
    for seed in (1, 2):
        strategy_sum, _ = load_full(study.model(seed))
        seed_mixes, _ = root_mixes(strategy_sum, tree, tables.bucket_count)
        mixes += seed_mixes / 2
        del strategy_sum
    rows = []
    for hand in hand_classes(tables):
        bucket = int(tables.bucket_of[colex_index(hand.cards)])
        row = {"hand": hand_text(hand.cards), "ranks": rank_text(hand.cards), "combos": hand.combos,
               "tier": hand.tier, "form": hwang_form(hand), "bucket": bucket, **features(hand.cards)}
        for seat, name in enumerate(FIRST_IN_POSITIONS):
            fold, limp, raise_ = (float(x) for x in mixes[seat, bucket])
            row[name] = {"fold": fold, "limp": limp, "open": raise_}
        rows.append(row)
    out = study.generated / "class_actions.json"
    out.write_text(json.dumps(rows))
    print(f"wrote {len(rows)} classes, {sum(r['combos'] for r in rows)} combos -> {out}")


if __name__ == "__main__":
    main()
