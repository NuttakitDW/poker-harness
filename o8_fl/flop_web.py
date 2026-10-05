"""Postflop data for the O8 page: the flop library and the flop strategy.

    .venv/bin/python -m o8_fl.flop_web library --count 200      (resumable, one file per flop)
    .venv/bin/python -m o8_fl.flop_web strategy --run tmp/o8_fl/run2

library writes public/static/o8-flops.json (id, board, texture of each flop) and one
o8-flop-<id>.bin per flop: gzip of the uint16 bucket of every four-card hand in class order
(flops.class_order), 65535 where the hand holds a board card. strategy writes o8-hu-flop.json: every
flop decision with its actions, the preflop line that leads to each flop root, and the flop strategy
of every bucket as base64 uint8 (probability x 255).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import time
from pathlib import Path

import numpy as np

from .buckets import Abstraction
from .cli import ABSTRACTION
from .flops import class_order, flop_buckets, flop_label, select_flops, texture
from .game import Rules
from .pool import DealPool
from .trainer import Trainer
from .tree import DECISION, PublicTree
from .web_export import ACTION, SLOT, _state, action_total

POOL = Path("tmp/o8_fl/pool.npz")
OUT = Path("public/static")


def build_library(count: int, out: Path, abstraction: Abstraction, centroids: np.ndarray, seed: int = 0) -> list[dict]:
    flops = select_flops(count, seed)
    index = [{"id": f"{i:03d}", "board": flop_label(f), "texture": list(texture(f))} for i, f in enumerate(flops)]
    out.mkdir(parents=True, exist_ok=True)
    (out / "o8-flops.json").write_text(json.dumps(index, separators=(",", ":")))
    order = class_order(abstraction)
    for entry, flop in zip(index, flops):
        path = out / f"o8-flop-{entry['id']}.bin"
        if path.exists():
            continue
        started = time.perf_counter()
        buckets = flop_buckets(np.array(flop), centroids, order, seed=seed * 1_000_003 + int(entry["id"]) * 1_000_000)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(buckets.astype("<u2").tobytes(), 9))
        tmp.replace(path)
        print(f"{entry['id']} {entry['board']}: {time.perf_counter() - started:.0f}s", flush=True)
    return index


def flop_nodes(tree: PublicTree) -> tuple[list[dict], dict[str, int], list[int]]:
    """Page nodes for every flop decision; roots maps 'preflop history' to its flop root node."""
    order = [n for n in range(tree.node_count) if tree.kind[n] == DECISION and tree.street[n] == 1]
    index = {node: i for i, node in enumerate(order)}
    nodes, roots = [], {}
    for node in order:
        state = _state(tree, node)
        history = tree.histories[node]
        if state.acted == frozenset() and state.bets == 0 and state.actor == 1:
            roots[history] = index[node]  # first flop decision after this preflop line
        options = []
        for action in state.legal():
            child = int(tree.children[node, SLOT[action]])
            option = {"action": ACTION[action], "total": action_total(state, action),
                      "all_in": False, "child": index.get(child, -1)}
            if option["child"] < 0:
                option["end"] = "hand over" if action == "f" else "turn"
            options.append(option)
        nodes.append({"actor": int(tree.actor[node]), "pot": float(sum(state.committed)), "behind": [0.0, 0.0],
                      "to_call": float(max(state.street_put) - state.street_put[state.actor]), "options": options})
    return nodes, roots, order


def export_strategy(trainer: Trainer, out: Path) -> dict:
    nodes, roots, order = flop_nodes(trainer.tree)
    buckets = trainer.bucket_counts[1]
    blobs = []
    for node in order:
        legal = [s for s in range(3) if trainer.tree.children[node, s] >= 0]
        rows = np.zeros((buckets, 3), dtype=np.uint8)
        for b in range(buckets):
            rows[b, :len(legal)] = np.round(trainer.average_policy(node, b)[legal] * 255).astype(np.uint8)
        blobs.append(rows.tobytes())
    data = {"iterations": trainer.iterations, "buckets": buckets, "seats": ["BTN", "BB"], "nodes": nodes,
            "roots": roots, "strategy": base64.b64encode(b"".join(blobs)).decode()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "o8-hu-flop.json").write_text(json.dumps(data, separators=(",", ":")))
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--pool", type=Path, default=POOL)
    parser.add_argument("--abstraction", type=Path, default=ABSTRACTION)
    sub = parser.add_subparsers(dest="command", required=True)
    lib = sub.add_parser("library")
    lib.add_argument("--count", type=int, default=200)
    strat = sub.add_parser("strategy")
    strat.add_argument("--run", type=Path, default=Path("tmp/o8_fl/run2"))
    strat.add_argument("--cap", type=int, default=5)
    args = parser.parse_args(argv)
    abstraction = Abstraction.cached(args.abstraction)
    pool = DealPool.load(args.pool)
    if args.command == "library":
        build_library(args.count, args.out, abstraction, pool.centroids[0])
    else:
        trainer = Trainer.load(args.run / "checkpoint.npz", PublicTree.build(Rules(cap=args.cap)), abstraction, pool)
        data = export_strategy(trainer, args.out)
        print(json.dumps({"iterations": data["iterations"], "flop_nodes": len(data["nodes"]), "roots": len(data["roots"])}))


if __name__ == "__main__":
    main()
