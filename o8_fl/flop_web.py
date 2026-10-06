"""Postflop data for the O8 page: flop and turn bucket tables and the strategy of every postflop decision.

The page's solve uses the strength buckets of o8_fl.strength (pool_v3), which depend only on hand and
board, so the tables are computed once for every board and the river buckets in the browser.

    .venv/bin/python -m o8_fl.flop_web library --out tmp/o8_fl/flops_v3                (1,755 flops)
    .venv/bin/python -m o8_fl.flop_web turns --out tmp/o8_fl/turns_v3 --workers 8      (resumable)
    .venv/bin/python -m o8_fl.flop_web strategy --run tmp/o8_fl/run4 --pool tmp/o8_fl/pool_v3.npz

library writes o8-flops.json (id, board, texture of every flop) and flop-<id>.bin: gzip of the uint16
bucket of every four-card hand in class order (flops.class_order), 65535 where the hand holds a board
card. turns writes turn-<flop id>-<card>.bin the same way for each turn card (card id 00-51 in the
library flop's suits). strategy writes o8-hu-post.json: every flop, turn and river decision with its
actions and street, the preflop history that leads to each flop root, and the average strategy of
every bucket (600 on flop and turn, 50 on the river) as base64 uint8 (probability x 255).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import time
from pathlib import Path

import numpy as np

from plo_premium_proof.tables import comb_table, five_card_ranks

from .buckets import Abstraction
from .cli import ABSTRACTION
from .flops import ALL_FLOPS, class_order, flop_label, select_flops, texture
from .game import Rules
from .pool import DealPool
from .ranges import COMBOS
from .strength import COUNTS, board_buckets
from .trainer import SLOTS, Trainer
from .tree import DECISION, PublicTree
from .web_export import ACTION, SLOT, _state, action_total

OUT = Path("public/static")


def _hands(abstraction: Abstraction) -> np.ndarray:
    return np.ascontiguousarray(COMBOS[class_order(abstraction)])


def _write(path: Path, buckets: np.ndarray) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(buckets.astype("<u2").tobytes(), 9))
    tmp.replace(path)


def build_library(out: Path, abstraction: Abstraction) -> list[dict]:
    flops = select_flops(ALL_FLOPS, 0)
    index = [{"id": f"{i:04d}", "board": flop_label(f), "texture": list(texture(f))} for i, f in enumerate(flops)]
    out.mkdir(parents=True, exist_ok=True)
    (out / "o8-flops.json").write_text(json.dumps(index, separators=(",", ":")))
    hands, rank5, comb = _hands(abstraction), five_card_ranks(), comb_table()
    for entry, flop in zip(index, flops):
        path = out / f"flop-{entry['id']}.bin"
        if not path.exists():
            _write(path, board_buckets(hands, np.asarray(flop, dtype=np.int64), 1, rank5, comb))
    return index


def build_turns(out: Path, library: Path, abstraction: Abstraction) -> int:
    """Turn tables for every library flop (board_buckets runs on all cores, so flops go one at a time)."""
    flops = json.loads((library / "o8-flops.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    hands, rank5, comb = _hands(abstraction), five_card_ranks(), comb_table()
    for entry in flops:
        text = entry["board"]
        flop = np.asarray([4 * "23456789TJQKA".index(text[i]) + "cdhs".index(text[i + 1]) for i in range(0, 6, 2)])
        started = time.perf_counter()
        for turn in range(52):
            path = out / f"turn-{entry['id']}-{turn:02d}.bin"
            if turn in flop or path.exists():
                continue
            _write(path, board_buckets(hands, np.append(flop, turn).astype(np.int64), 2, rank5, comb))
        print(f"{entry['id']} {text}: {time.perf_counter() - started:.0f}s", flush=True)
    return len(flops)


def post_nodes(tree: PublicTree) -> tuple[list[dict], dict[str, int], list[int]]:
    """Page nodes for every flop, turn and river decision; roots maps the preflop history to the flop root."""
    order = [n for n in range(tree.node_count) if tree.kind[n] == DECISION and tree.street[n] >= 1]
    index = {node: i for i, node in enumerate(order)}
    nodes, roots = [], {}
    for node in order:
        state = _state(tree, node)
        if tree.street[node] == 1 and state.acted == frozenset() and state.bets == 0 and state.actor == 1:
            roots[tree.histories[node]] = index[node]  # first flop decision after this preflop line
        options = []
        for action in state.legal():
            child = int(tree.children[node, SLOT[action]])
            option = {"action": ACTION[action], "total": action_total(state, action),
                      "all_in": False, "child": index.get(child, -1)}
            if option["child"] < 0:
                option["end"] = "hand over" if action == "f" else "showdown"
            options.append(option)
        nodes.append({"actor": int(tree.actor[node]), "street": int(tree.street[node]),
                      "pot": float(sum(state.committed)), "behind": [0.0, 0.0],
                      "to_call": float(max(state.street_put) - state.street_put[state.actor]), "options": options})
    return nodes, roots, order


def export_strategy(trainer: Trainer, out: Path) -> dict:
    tree = trainer.tree
    nodes, roots, order = post_nodes(tree)
    blobs = []
    for node in order:
        count = COUNTS[int(tree.street[node]) - 1]
        legal = np.flatnonzero(tree.children[node] >= 0)
        base = int(trainer.offsets[node])
        block = trainer.strategy_sum[base:base + count * SLOTS].reshape(count, SLOTS)[:, legal]
        sums = block.sum(axis=1, keepdims=True)
        policy = np.where(sums > 0, block / np.where(sums > 0, sums, 1), 1.0 / len(legal))
        rows = np.zeros((count, 3), dtype=np.uint8)
        rows[:, :len(legal)] = np.rint(policy * 255).astype(np.uint8)
        blobs.append(rows.tobytes())
    data = {"iterations": trainer.iterations, "buckets": list(COUNTS), "seats": ["BTN", "BB"], "nodes": nodes,
            "roots": roots, "strategy": base64.b64encode(b"".join(blobs)).decode()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "o8-hu-post.json").write_text(json.dumps(data, separators=(",", ":")))
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--abstraction", type=Path, default=ABSTRACTION)
    sub = parser.add_subparsers(dest="command", required=True)
    lib = sub.add_parser("library")
    lib.add_argument("--out", type=Path, default=Path("tmp/o8_fl/flops_v3"))
    turns = sub.add_parser("turns")
    turns.add_argument("--out", type=Path, default=Path("tmp/o8_fl/turns_v3"))
    turns.add_argument("--library", type=Path, default=Path("tmp/o8_fl/flops_v3"))
    strat = sub.add_parser("strategy")
    strat.add_argument("--run", type=Path, default=Path("tmp/o8_fl/run4"))
    strat.add_argument("--pool", type=Path, default=Path("tmp/o8_fl/pool_v3.npz"))
    strat.add_argument("--cap", type=int, default=5)
    strat.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    abstraction = Abstraction.cached(args.abstraction)
    if args.command == "library":
        print(f"{len(build_library(args.out, abstraction))} flops")
    elif args.command == "turns":
        print(f"{build_turns(args.out, args.library, abstraction)} flops")
    else:
        pool = DealPool.load(args.pool)
        trainer = Trainer.load(args.run / "checkpoint.npz", PublicTree.build(Rules(cap=args.cap)), abstraction, pool)
        data = export_strategy(trainer, args.out)
        size = (args.out / "o8-hu-post.json").stat().st_size / 1e6
        streets = [sum(n["street"] == s for n in data["nodes"]) for s in (1, 2, 3)]
        print(json.dumps({"iterations": data["iterations"], "nodes": streets, "roots": len(data["roots"]), "mb": round(size, 2)}))


if __name__ == "__main__":
    main()
