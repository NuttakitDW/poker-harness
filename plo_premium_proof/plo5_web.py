"""Publish the PLO5 ICM solves (plo_premium_proof.review) for the site's spot library (public/plo5.html).

Writes, under --out:
  plo5-spots.json      the library: one row per spot (seats, stacks, players left, field stack, quality)
  spot-<id>.json       one solve in the range explorer's format: the preflop tree for heads-up lines with
                       every bucket's average strategy (uint8, base64)
  plo5-classes.json    every PLO5 suit class: cards, suit shape, combos, bucket, equity band

Only the solver's output goes out: no hand history, hole cards or player names.

    .venv/bin/python -m plo_premium_proof.plo5_web --out tmp/plo5/web
"""

from __future__ import annotations

import argparse
import base64
import collections
import json
from pathlib import Path

import numpy as np

from plo_equity.cards import card_text

from .finaltable import FinalTableSpec
from .fulltree import FullTree
from .plo5 import Plo5Tables
from .review import OUT as REVIEW
from .web_export import heads_up_tree

SHAPES = {(2, 1, 1, 1): "ss", (2, 2, 1): "ds", (3, 1, 1): "3f", (3, 2): "3+2", (4, 1): "4f", (5,): "5f"}
BANDS = ("Top 10%", "10-25%", "25-50%", "Bottom 50%")


def export_classes(out: Path, tables: Plo5Tables) -> int:
    weights = tables.combos.astype(np.float64)
    order = np.argsort(-tables.equity[:, 0], kind="stable")
    cum = np.cumsum(weights[order]) / weights.sum()
    band = np.empty(len(order), dtype=np.int64)
    band[order] = np.searchsorted([0.10, 0.25, 0.50], cum, side="left")
    rows = []
    for cls in range(len(tables.reps)):
        cards = card_text(tuple(int(c) for c in tables.reps[cls]))
        suits = collections.Counter(cards[1::2])
        rows.append([cards, SHAPES[tuple(sorted(suits.values(), reverse=True))], int(tables.combos[cls]),
                     int(tables.class_bucket[cls]), int(band[cls])])
    (out / "plo5-classes.json").write_text(json.dumps({"tiers": list(BANDS), "rows": rows}, separators=(",", ":")))
    return len(rows)


def export_spot(folder: Path, out: Path) -> dict | None:
    review = json.loads((folder / "review.json").read_text())
    spec = FinalTableSpec.from_dict(review["spec"])
    tree = FullTree.build(spec.tree_config(), cache_dir=None)
    policy = np.load(folder / "policy.npz")["policy"]
    buckets = 1000

    def rows_of(node: int) -> np.ndarray:
        start = int(tree.row_start[tree.decision_index[node]])
        return policy[start:start + buckets]

    nodes, blob = heads_up_tree(spec.tree_config().root(), tree.actor, tree.children, tree.action_ids,
                                tree.action_count, rows_of, spec.seat_names)
    spot_id = folder.name.lower()
    n = len(spec.stacks)
    stacks = [round(x, 1) for x in spec.stacks]
    left = spec.players_left or n
    label = f"{n}-handed · {left} left · avg {round(sum(stacks) / n)}bb"
    detail = (" · ".join(f"{name} {x:g}" for name, x in zip(spec.seat_names, stacks))
              + f" · ante {spec.ante_bb:g}bb · ICM, {left} of 57 left, 9 paid"
              + (f" · other tables avg {spec.field_stack_bb:.0f}bb" if spec.field_stack_bb else ""))
    data = {"name": spot_id, "label": label, "detail": detail, "stack": max(stacks), "ante": spec.ante_bb,
            "buckets": buckets, "seats": list(spec.seat_names), "nodes": nodes,
            "strategy": base64.b64encode(blob).decode(), "meta": {k: review["meta"].get(k) for k in
                                                                   ("deals", "seconds", "quality", "nodes")}}
    (out / f"spot-{spot_id}.json").write_text(json.dumps(data, separators=(",", ":")))
    return {"id": spot_id, "seats": list(spec.seat_names), "stacks": stacks, "avg": round(sum(stacks) / n, 1),
            "left": left, "field": round(spec.field_stack_bb, 1), "ante": spec.ante_bb, "players": n,
            "quality": review["meta"].get("quality"), "deals": review["meta"].get("deals")}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("tmp/plo5/web"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"{export_classes(args.out, Plo5Tables())} classes")
    spots = []
    for folder in sorted(REVIEW.iterdir()):
        if (folder / "review.json").exists() and (folder / "policy.npz").exists():
            row = export_spot(folder, args.out)
            if row:
                spots.append(row)
                print(folder.name, row["players"], row["left"], row["quality"], flush=True)
    spots.sort(key=lambda s: (-s["left"], s["players"]))
    library = {"tournament": {"entries": 57, "paid": 9, "start_stack": 10000,
                              "payouts": [113.80, 93.78, 77.31, 63.73, 52.53, 43.30, 35.70, 24.26, 19.99]},
               "spots": spots}
    (args.out / "plo5-spots.json").write_text(json.dumps(library, separators=(",", ":")))
    print(f"{len(spots)} spots")


if __name__ == "__main__":
    main()
