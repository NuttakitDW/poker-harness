"""Postflop data for the PLO4 page: flop and turn bucket tables and each game's postflop strategy.

    .venv/bin/python -m plo_premium_proof.flop_web library --out tmp/plo_premium_proof/flops   (resumable)
    .venv/bin/python -m plo_premium_proof.flop_web turns --out tmp/plo_premium_proof/turns     (resumable, ~2 h)
    .venv/bin/python -m plo_premium_proof.flop_web strategy --name 6max-10bb --models <seed-1 model> <seed-2 model>

library writes plo-flops.json (id, board, texture of each of the 1,755 suit-distinct flops, the same ids as
the O8 library) and one flop-<id>.bin per flop: gzip of the uint16 flop bucket (plo_premium_proof.postflop,
120 buckets) of every four-card hand in plo-classes.json order, 65535 where the hand holds a board card.
The buckets depend only on hand and board, so one library serves every table size and stack.
turns writes turn-<flop id>-<card>.bin the same way for every turn card (card id 00-51 in the library
flop's suits). River buckets are only hand strength (10 bins), so the page computes them itself.

strategy writes plo-<name>-post.json: every flop, turn and river decision after the page's preflop lines, the
preflop history (explorer letters) that leads to each flop root, and the seed-averaged strategy of every
bucket (120 on flop and turn, 10 on the river) as base64 uint8 (probability x 255).
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
def street_buckets(hands: np.ndarray, board: np.ndarray, street: int, rank5: np.ndarray, comb: np.ndarray) -> np.ndarray:
    """Flop (street 1) or turn (street 2) bucket of every hand; ``board`` holds street + 2 cards."""
    shown = street + 2
    distribution = np.empty(1326, dtype=np.int64)
    count = board_distribution(board, shown, rank5, comb, distribution)
    out = np.empty(hands.shape[0], dtype=np.uint16)
    for i in range(hands.shape[0]):
        hole = hands[i]
        clash = False
        for card in hole:
            for k in range(shown):
                if card == board[k]:
                    clash = True
        out[i] = NO_BUCKET if clash else postflop_bucket(hole, board, street, distribution, count, rank5, comb)
    return out


def flop_buckets(hands: np.ndarray, board: np.ndarray, rank5: np.ndarray, comb: np.ndarray) -> np.ndarray:
    return street_buckets(hands, board, 1, rank5, comb)


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


def _turn_worker(job: tuple[str, str, str]) -> str:
    """Write turn-<flop id>-<card>.bin for every turn card of one flop (card = id 00-51, library suits)."""
    flop_id, board_text, out_text = job
    out = Path(out_text)
    hands, rank5, comb = _WORKER["hands"], _WORKER["rank5"], _WORKER["comb"]
    flop = parse_board(board_text)
    started = time.perf_counter()
    for turn in range(52):
        if turn in flop:
            continue
        path = out / f"turn-{flop_id}-{turn:02d}.bin"
        if path.exists():
            continue
        buckets = street_buckets(hands, np.append(flop, turn), 2, rank5, comb)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(buckets.astype("<u2").tobytes(), 9))
        tmp.replace(path)
    return f"{flop_id} {board_text}: {time.perf_counter() - started:.0f}s"


_WORKER: dict = {}


def _turn_init() -> None:
    _WORKER.update(hands=class_order(), rank5=five_card_ranks(), comb=comb_table())


def build_turns(out: Path, workers: int) -> int:
    """Turn bucket tables for every flop of the library: 1,755 x 49 files, resumable."""
    from multiprocessing import Pool
    flops = json.loads(O8_FLOPS.read_text())
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(entry["id"], entry["board"], str(out)) for entry in flops]
    with Pool(workers, initializer=_turn_init) as pool:
        for line in pool.imap_unordered(_turn_worker, jobs):
            print(line, flush=True)
    return len(jobs)


def post_tree(tree, root: PLOState) -> tuple[list[dict], dict[str, int], list[int]]:
    """Page nodes for every flop, turn and river decision after the page's preflop lines
    (web_export.heads_up_tree); roots maps each preflop history to its first flop decision."""
    nodes: list[dict] = []
    order: list[int] = []
    roots: dict[str, int] = {}

    def visit_post(node: int, state: PLOState) -> int:
        index = len(nodes)
        seat = int(tree.actor[node])
        item = {"actor": seat, "street": int(tree.street[node]), "pot": round(float(state.pot), 4),
                "behind": [round(float(b), 4) for b in state.behind],
                "to_call": round(max(0.0, state.current_bet - state.street_put[seat]), 4), "options": []}
        nodes.append(item)
        order.append(node)
        for slot in range(int(tree.action_count[node])):
            action = ACTION_NAMES[int(tree.action_ids[node, slot])]
            amount = state.action_amount(Action(action))
            after = state.apply(Action(action))
            child = int(tree.children[node, slot])
            option = {"action": action, "total": round(float(state.street_put[seat] + amount), 4),
                      "all_in": bool(amount > 0 and abs(amount - state.behind[seat]) < 1e-9), "child": -1}
            item["options"].append(option)
            if child >= 0 and tree.actor[child] >= 0:
                option["child"] = visit_post(child, after)
            else:
                option["end"] = "hand over" if after.terminal and len(after.live) == 1 else "showdown"
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
                roots[line] = visit_post(child, after)

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
    nodes, roots, order = post_tree(tree, config.root())
    sizes = [STREET_BUCKETS[node["street"]] for node in nodes]
    total = [np.zeros((size, 3)) for size in sizes]
    for path in models:
        strategy_sum, _ = load_full(path)
        for i, node in enumerate(order):
            start = int(tree.row_start[tree.decision_index[node]])
            count = int(tree.action_count[node])
            block = np.asarray(strategy_sum[start:start + sizes[i], :count], dtype=np.float64)
            sums = block.sum(axis=1, keepdims=True)
            total[i][:, :count] += np.where(sums > 0, block / np.where(sums > 0, sums, 1), 1.0 / count)
        del strategy_sum
    blob = b"".join(np.rint(rows / len(models) * 255).astype(np.uint8).tobytes() for rows in total)
    data = {"name": name, "seeds": len(models), "buckets": list(STREET_BUCKETS[1:]), "nodes": nodes, "roots": roots,
            "strategy": base64.b64encode(blob).decode()}
    out.mkdir(parents=True, exist_ok=True)
    (out / f"plo-{name}-post.json").write_text(json.dumps(data, separators=(",", ":")))
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lib = sub.add_parser("library")
    lib.add_argument("--out", type=Path, required=True)
    turns = sub.add_parser("turns")
    turns.add_argument("--out", type=Path, required=True)
    turns.add_argument("--workers", type=int, default=8)
    strat = sub.add_parser("strategy")
    strat.add_argument("--name", required=True, help="game name, e.g. 6max-10bb")
    strat.add_argument("--models", type=Path, nargs="+", required=True)
    strat.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.command == "library":
        print(f"{build_library(args.out)} flops")
    elif args.command == "turns":
        print(f"{build_turns(args.out, args.workers)} flops")
    else:
        data = export_strategy(args.name, args.models, args.out)
        size = (args.out / f"plo-{args.name}-post.json").stat().st_size / 1e6
        streets = [sum(node["street"] == s for node in data["nodes"]) for s in (1, 2, 3)]
        print(f"plo-{args.name}-post.json: flop/turn/river nodes {streets}, {len(data['roots'])} roots, {size:.2f} MB")


if __name__ == "__main__":
    main()
