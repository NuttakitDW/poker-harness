"""Export the solved preflop trees for the browser range explorer (public/plo.html).

For each chart this writes <out>/plo-<name>.json: every preflop decision reachable while at
most two players have voluntarily put chips in (the heads-up tree), with each node's actor,
actions, bet sizes, stacks, pot, the child each action leads to, and the 780-bucket average
strategy as base64 uint8 (probability x 255). It also writes <out>/plo-classes.json: every
suit-isomorphism class of four-card hands (16,432) with its combos, bucket and Hwang tier,
which the page aggregates into the rank matrix.

Usage: python -m plo_premium_proof.web_export --out public/static [--only 6max-100bb]
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

TABLE_SIZES = (6, 5, 4, 3, 2)
STACKS = (100, 40, 20)
# Every chart from scripts/final_table/chart_batch.py: each seat has the stack behind after
# posting the ante, and the ante stays out of the preflop pot-limit size.
GAMES = {
    f"{seats}max-{stack}bb": {"label": f"{seats}-max · {stack}bb", "seats": seats, "stack_label": stack,
                              "detail": f"{seats}-max · {stack}bb behind after a 0.116bb ante each · "
                                        "ante not in the preflop pot size · chip EV"}
    for seats in TABLE_SIZES for stack in STACKS
}
# Seat names in preflop order for each table size (six-max keeps preflop_chart.SEATS).
SEAT_NAMES = {2: ("SB", "BB"), 3: ("BTN", "SB", "BB"), 4: ("CO", "BTN", "SB", "BB"),
              5: ("HJ", "CO", "BTN", "SB", "BB"), 6: SEATS}
MAX_ACTIVE = 2  # the page covers heads-up lines; a third player entering ends the tree
SHAPES = {(2, 2): "ds", (2, 1, 1): "ss", (1, 1, 1, 1): "rb", (3, 1): "3f", (4,): "mono"}
TIERS = ("Premium", "Speculative", "Marginal", "Trash")


def heads_up_tree(root: PLOState, actor, children, action_ids, action_count, rows_of,
                  seat_names: tuple[str, ...]) -> tuple[list[dict], bytes]:
    """Preflop decisions reachable while at most two players have put chips in voluntarily.

    ``rows_of(node)`` gives the node's (buckets, 3) uint8 strategy (probability x 255).
    Returns the page's node list and the concatenated strategy bytes, in node order.
    """
    nodes: list[dict] = []
    blobs: list[bytes] = []
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 10_000))

    def visit(node: int, state: PLOState, active: frozenset) -> int:
        index = len(nodes)
        seat = int(actor[node])
        entry = {"actor": seat, "pot": round(float(state.pot), 4),
                 "behind": [round(float(b), 4) for b in state.behind],
                 "to_call": round(max(0.0, state.current_bet - state.street_put[seat]), 4), "options": []}
        nodes.append(entry)
        count = int(action_count[node])
        source = rows_of(node)
        rows = np.zeros((source.shape[0], 3), dtype=np.uint8)
        rows[:, :count] = source[:, :count]
        blobs.append(rows.tobytes())
        for slot in range(count):
            action = ACTION_NAMES[int(action_ids[node, slot])]
            amount = state.action_amount(Action(action))
            joined = active | {seat} if action in ("call", "pot") else active
            after = state.apply(Action(action))
            child = int(children[node, slot])
            if child >= 0 and len(joined) <= MAX_ACTIVE and not after.terminal and after.street == 0:
                target = visit(child, after, joined)
                end = None
            else:
                target = -1
                end = ("multiway" if len(joined) > MAX_ACTIVE
                       else "hand over" if after.terminal and len(after.live) == 1
                       else "flop")
            entry["options"].append({
                "action": action, "total": round(float(state.street_put[seat] + amount), 4),
                "all_in": bool(amount > 0 and abs(amount - state.behind[seat]) < 1e-9),
                "child": target, **({"end": end} if end else {}),
            })
        return index

    try:
        visit(0, root, frozenset())
    finally:
        sys.setrecursionlimit(limit)
    return nodes, b"".join(blobs)


def export_game(name: str, out_dir: Path) -> dict:
    book = chart(name)
    seats = SEAT_NAMES[book.seats]
    root = PLOState.new((book.start_stack,) * book.seats, sb=0.5, bb=1.0, ante=book.ante, ante_mode="individual",
                        opening_raise_mode="pot_only")
    nodes, blob = heads_up_tree(root, book.actor, book.children, book.action_ids, book.action_count,
                                lambda node: book.strategy[node], seats)
    game = GAMES[name]
    if book.seats != game["seats"] or book.stack != game["stack_label"]:
        raise ValueError(f"chart {name} holds {book.seats} seats at {book.stack:g}bb")
    data = {"name": name, "label": game["label"], "detail": game["detail"], "stack": book.stack, "ante": book.ante,
            "deals_per_seed": book.meta.get("deals_per_seed"), "seeds": book.meta.get("seeds"),
            "buckets": int(book.strategy.shape[1]), "seats": list(seats), "nodes": nodes,
            "strategy": base64.b64encode(blob).decode()}
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
    parser.add_argument("--only", nargs="+", help="export just these charts, e.g. 6max-100bb")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    names = args.only or list(GAMES)
    unknown = sorted(set(names) - set(GAMES))
    if unknown:
        parser.error(f"unknown charts: {unknown}")
    for name in names:
        data = export_game(name, args.out)
        print(f"plo-{name}.json: {len(data['nodes'])} nodes, "
              f"{(args.out / f'plo-{name}.json').stat().st_size / 1e6:.2f} MB")
    count = export_classes(args.out)
    print(f"plo-classes.json: {count} classes, {(args.out / 'plo-classes.json').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
