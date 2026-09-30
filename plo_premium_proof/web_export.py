"""Export the solved preflop trees for the browser range explorer (public/plo.html).

For each chart this writes <out>/plo-<name>.json: every preflop decision reachable while at
most two players have voluntarily put chips in (the heads-up tree), with each node's actor,
actions, bet sizes, stacks, pot, the child each action leads to, and the 780-bucket average
strategy as base64 uint8 (probability x 255). It also writes <out>/plo-classes.json: every
suit-isomorphism class of four-card hands (16,432) with its combos, bucket and Hwang tier,
which the page aggregates into the rank matrix.

Usage: python -m plo_premium_proof.web_export --out public/static
"""

from __future__ import annotations

import argparse
import base64
import collections
import json
import sys
from pathlib import Path

import numpy as np

from plo_icm.game import Action, PLOState

from .preflop_chart import ACTION_NAMES, SEATS, chart

GAMES = {
    "20bb": {"label": "20bb", "detail": "6-max · 20bb · no ante · chip EV"},
    "mtt40": {"label": "40bb MTT", "detail": "6-max · 40bb · ante 0.116bb each, excluded from preflop pot size · chip EV"},
}
MAX_ACTIVE = 2  # the page covers heads-up lines; a third player entering ends the tree
SHAPES = {(2, 2): "ds", (2, 1, 1): "ss", (1, 1, 1, 1): "rb", (3, 1): "3f", (4,): "mono"}
TIERS = ("Premium", "Speculative", "Marginal", "Trash")


def export_game(name: str, out_dir: Path) -> dict:
    book = chart(name)
    nodes: list[dict] = []
    blobs: list[bytes] = []
    local: dict[int, int] = {}
    sys.setrecursionlimit(10_000)

    def visit(node: int, state: PLOState, active: frozenset) -> int:
        index = len(nodes)
        local[node] = index
        seat = int(book.actor[node])
        entry = {"actor": seat, "pot": round(float(state.pot), 4),
                 "behind": [round(float(b), 4) for b in state.behind],
                 "to_call": round(max(0.0, state.current_bet - state.street_put[seat]), 4), "options": []}
        nodes.append(entry)
        rows = np.zeros((book.strategy.shape[1], 3), dtype=np.uint8)
        count = int(book.action_count[node])
        rows[:, :count] = book.strategy[node, :, :count]
        blobs.append(rows.tobytes())
        for slot in range(count):
            action = ACTION_NAMES[int(book.action_ids[node, slot])]
            amount = state.action_amount(Action(action))
            joined = active | {seat} if action in ("call", "pot") else active
            after = state.apply(Action(action))
            child = int(book.children[node, slot])
            if child >= 0 and len(joined) <= MAX_ACTIVE and not after.terminal and after.street == 0:
                target = visit(child, after, joined)
                end = None
            else:
                target = -1
                end = ("multiway" if len(joined) > MAX_ACTIVE
                       else "hand over" if after.terminal and len([s for s in range(6) if s not in after.folded]) == 1
                       else "flop")
            entry["options"].append({
                "action": action, "total": round(float(state.street_put[seat] + amount), 4),
                "all_in": bool(amount > 0 and abs(amount - state.behind[seat]) < 1e-9),
                "child": target, **({"end": end} if end else {}),
            })
        return index

    root = PLOState.new((book.stack,) * 6, sb=0.5, bb=1.0, ante=book.ante, ante_mode="individual",
                        opening_raise_mode="pot_only")
    visit(0, root, frozenset())
    data = {"name": name, **GAMES[name], "stack": book.stack, "ante": book.ante,
            "deals_per_seed": book.meta.get("deals_per_seed"), "seeds": book.meta.get("seeds"),
            "buckets": int(book.strategy.shape[1]), "seats": list(SEATS), "nodes": nodes,
            "strategy": base64.b64encode(b"".join(blobs)).decode()}
    (out_dir / f"plo-{name}.json").write_text(json.dumps(data, separators=(",", ":")))
    return data


def export_classes(out_dir: Path) -> int:
    # solver modules, imported here so the chart reader stays light
    from plo_equity.cards import card_text

    from .tables import HandTables, colex_index, hand_classes
    tables = HandTables.build()
    rows = []
    for hand in hand_classes(tables):
        cards = card_text(hand.cards)
        suits = collections.Counter(cards[1::2])
        shape = SHAPES[tuple(sorted(suits.values(), reverse=True))]
        bucket = int(tables.bucket_of[colex_index(hand.cards)])
        rows.append([cards, shape, hand.combos, bucket, TIERS.index(hand.tier)])
    (out_dir / "plo-classes.json").write_text(json.dumps({"tiers": TIERS, "rows": rows}, separators=(",", ":")))
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name in GAMES:
        data = export_game(name, args.out)
        print(f"plo-{name}.json: {len(data['nodes'])} nodes, "
              f"{(args.out / f'plo-{name}.json').stat().st_size / 1e6:.2f} MB")
    count = export_classes(args.out)
    print(f"plo-classes.json: {count} classes, {(args.out / 'plo-classes.json').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
