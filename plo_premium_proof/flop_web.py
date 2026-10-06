"""Postflop data for the PLO4 page: the flop library and each game's flop strategy.

    .venv/bin/python -m plo_premium_proof.flop_web library --out tmp/plo_premium_proof/flops   (resumable)
    .venv/bin/python -m plo_premium_proof.flop_web strategy --name 6max-10bb --models <seed-1 model> <seed-2 model>

library writes plo-flops.json (id, board, texture of each of the 1,755 suit-distinct flops, the same ids as
the O8 library) and one flop-<id>.bin per flop: gzip of the uint16 flop bucket (plo_premium_proof.postflop,
120 buckets) of every four-card hand in plo-classes.json order, 65535 where the hand holds a board card.
The buckets depend only on hand and board, so one library serves every table size and stack.

strategy writes plo-<name>-flop.json: every flop decision reachable from the page's preflop lines, the
preflop history (explorer letters) that leads to each flop root, and the seed-averaged flop strategy of
every bucket as base64 uint8 (probability x 255).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
from numba import njit

from plo_equity.cards import RANKS, SUITS, canonical_hand
from plo_icm.game import Action, PLOState

from .postflop import board_distribution, postflop_bucket
from .preflop_chart import ACTION_NAMES
from .tables import comb_table, five_card_ranks
from .web_export import MAX_ACTIVE

OUT = Path("public/static")
O8_FLOPS = Path("public/static/o8-flops.json")  # the same 1,755 flops, so ids line up across games
NO_BUCKET = 65535
LETTER = {"fold": "f", "check": "k", "call": "c", "pot": "r"}  # plo-explorer.js LETTER


def class_order() -> np.ndarray:
    """Every four-card hand as card ids, grouped by suit class in plo-classes.json row order."""
    groups: dict[tuple[int, ...], list[tuple[int, ...]]] = {}
    for cards in itertools.combinations(range(52), 4):
        groups.setdefault(canonical_hand(cards), []).append(cards)
    return np.asarray([hand for key in sorted(groups) for hand in groups[key]], dtype=np.int64)


@njit(cache=True)  # pragma: no cover - compiled native code
def flop_buckets(hands: np.ndarray, board: np.ndarray, rank5: np.ndarray, comb: np.ndarray) -> np.ndarray:
    distribution = np.empty(1326, dtype=np.int64)
    count = board_distribution(board, 3, rank5, comb, distribution)
    out = np.empty(hands.shape[0], dtype=np.uint16)
    for i in range(hands.shape[0]):
        hole = hands[i]
        clash = False
        for card in hole:
            if card == board[0] or card == board[1] or card == board[2]:
                clash = True
        out[i] = NO_BUCKET if clash else postflop_bucket(hole, board, 1, distribution, count, rank5, comb)
    return out


def parse_board(text: str) -> np.ndarray:
    return np.asarray([4 * RANKS.index(text[i]) + SUITS.index(text[i + 1]) for i in range(0, 6, 2)], dtype=np.int64)


def build_library(out: Path) -> int:
    flops = json.loads(O8_FLOPS.read_text())
    out.mkdir(parents=True, exist_ok=True)
    (out / "plo-flops.json").write_text(json.dumps(flops, separators=(",", ":")))
    hands = class_order()
    rank5, comb = five_card_ranks(), comb_table()
    for entry in flops:
        path = out / f"flop-{entry['id']}.bin"
        if path.exists():
            continue
        started = time.perf_counter()
        buckets = flop_buckets(hands, parse_board(entry["board"]), rank5, comb)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(buckets.astype("<u2").tobytes(), 9))
        tmp.replace(path)
        print(f"{entry['id']} {entry['board']}: {time.perf_counter() - started:.1f}s", flush=True)
    return len(flops)


def flop_tree(tree, root: PLOState) -> tuple[list[dict], dict[str, int], list[int]]:
    """Page nodes for every flop decision after the page's preflop lines (web_export.heads_up_tree)."""
    nodes: list[dict] = []
    order: list[int] = []
    roots: dict[str, int] = {}

    def entry(node: int, state: PLOState) -> dict:
        seat = int(tree.actor[node])
        return {"actor": seat, "pot": round(float(state.pot), 4), "behind": [round(float(b), 4) for b in state.behind],
                "to_call": round(max(0.0, state.current_bet - state.street_put[seat]), 4), "options": []}

    def visit_flop(node: int, state: PLOState) -> int:
        index = len(nodes)
        item = entry(node, state)
        nodes.append(item)
        order.append(node)
        seat = item["actor"]
        for slot in range(int(tree.action_count[node])):
            action = ACTION_NAMES[int(tree.action_ids[node, slot])]
            amount = state.action_amount(Action(action))
            after = state.apply(Action(action))
            child = int(tree.children[node, slot])
            option = {"action": action, "total": round(float(state.street_put[seat] + amount), 4),
                      "all_in": bool(amount > 0 and abs(amount - state.behind[seat]) < 1e-9)}
            if child >= 0 and tree.actor[child] >= 0 and tree.street[child] == 1:
                option["child"] = -1  # filled below, after the child's index is known
                item["options"].append(option)
                option["child"] = visit_flop(child, after)
            else:
                option.update(child=-1, end="hand over" if after.terminal and len(after.live) == 1 else "turn")
                item["options"].append(option)
        return index

    def visit_preflop(node: int, state: PLOState, active: frozenset, history: str) -> None:
        seat = int(tree.actor[node])
        for slot in range(int(tree.action_count[node])):
            action = ACTION_NAMES[int(tree.action_ids[node, slot])]
            joined = active | {seat} if action in ("call", "pot") else active
            after = state.apply(Action(action))
            child = int(tree.children[node, slot])
            line = history + LETTER[action]
            if child < 0 or len(joined) > MAX_ACTIVE:
                continue
            if not after.terminal and after.street == 0:
                visit_preflop(child, after, joined, line)
            elif tree.actor[child] >= 0 and tree.street[child] == 1:
                roots[line] = visit_flop(child, after)

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 10_000))
    try:
        visit_preflop(0, root, frozenset(), "")
    finally:
        sys.setrecursionlimit(limit)
    return nodes, roots, order


def export_strategy(name: str, models: list[Path], out: Path) -> dict:
    from .fullsolve import load_full, meta_tree_config  # numba-heavy; only the exporter needs them
    from .fulltree import STREET_BUCKETS, FullTree
    with np.load(models[0]) as data:
        meta = json.loads(str(data["meta"]))
    config = meta_tree_config(meta)
    tree = FullTree.build(config)
    nodes, roots, order = flop_tree(tree, config.root())
    buckets = STREET_BUCKETS[1]
    total = np.zeros((len(order), buckets, 3))
    for path in models:
        strategy_sum, _ = load_full(path)
        for i, node in enumerate(order):
            start = int(tree.row_start[tree.decision_index[node]])
            count = int(tree.action_count[node])
            block = np.asarray(strategy_sum[start:start + buckets, :count], dtype=np.float64)
            sums = block.sum(axis=1, keepdims=True)
            total[i, :, :count] += np.where(sums > 0, block / np.where(sums > 0, sums, 1), 1.0 / count)
        del strategy_sum
    mix = np.rint(total / len(models) * 255).astype(np.uint8)
    data = {"name": name, "seeds": len(models), "buckets": buckets, "nodes": nodes, "roots": roots,
            "strategy": base64.b64encode(mix.tobytes()).decode()}
    out.mkdir(parents=True, exist_ok=True)
    (out / f"plo-{name}-flop.json").write_text(json.dumps(data, separators=(",", ":")))
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lib = sub.add_parser("library")
    lib.add_argument("--out", type=Path, required=True)
    strat = sub.add_parser("strategy")
    strat.add_argument("--name", required=True, help="game name, e.g. 6max-10bb")
    strat.add_argument("--models", type=Path, nargs="+", required=True)
    strat.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.command == "library":
        print(f"{build_library(args.out)} flops")
    else:
        data = export_strategy(args.name, args.models, args.out)
        size = (args.out / f"plo-{args.name}-flop.json").stat().st_size / 1e6
        print(f"plo-{args.name}-flop.json: {len(data['nodes'])} flop nodes, {len(data['roots'])} roots, {size:.2f} MB")


if __name__ == "__main__":
    main()
