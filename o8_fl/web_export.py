"""Export the trained preflop strategy for the browser range explorer (public/o8.html).

Writes <out>/o8-hu.json (every preflop decision with its actions, the child each leads to, and the
strategy of all 16,432 hand classes as base64 uint8, probability x 255) and <out>/o8-classes.json
(each class's cards, suit shape, combos, bucket = its own index, and low-card group). Same format as
the PLO explorer files, so the page reuses public/static/plo-explorer.js.

    .venv/bin/python -m o8_fl.web_export --run tmp/o8_fl/run1 --out public/static
"""

from __future__ import annotations

import argparse
import base64
import collections
import json
from pathlib import Path

import numpy as np

from .buckets import Abstraction
from .cli import ABSTRACTION
from .game import BettingState, Rules
from .pool import DealPool
from .trainer import Trainer
from .tree import DECISION, PublicTree

SHAPES = {(2, 2): "ds", (2, 1, 1): "ss", (1, 1, 1, 1): "rb", (3, 1): "3f", (4,): "mono"}
# Low-card groups shown as filter chips; index = position in this tuple.
GROUPS = ("A-2", "A-3", "A กับไพ่ต่ำอื่น", "ไพ่ต่ำไม่มี A", "ไพ่สูงล้วน")
ACTION = {"f": "fold", "k": "check", "c": "call", "b": "raise", "r": "raise"}
SLOT = {"f": 0, "k": 1, "c": 1, "b": 2, "r": 2}


def low_group(cards: str) -> int:
    ranks = {cards[i] for i in range(0, len(cards), 2)}
    lows = ranks & set("A2345678")
    if {"A", "2"} <= ranks:
        return 0
    if {"A", "3"} <= ranks:
        return 1
    if "A" in ranks and len(lows) >= 2:
        return 2
    if len(lows - {"A"}) >= 2:
        return 3
    return 4


def preflop_nodes(tree: PublicTree) -> tuple[list[dict], list[int]]:
    """Explorer nodes for every preflop decision, and the tree node behind each one."""
    order = [n for n in range(tree.node_count) if tree.kind[n] == DECISION and tree.street[n] == 0]
    index = {node: i for i, node in enumerate(order)}
    nodes = []
    for node in order:
        state = _state(tree, node)
        options = []
        for action in state.legal():
            child = int(tree.children[node, SLOT[action]])
            after = state.apply(action)
            option = {"action": ACTION[action], "total": max(after.street_put) if action != "f" else state.street_put[state.actor],
                      "all_in": False, "child": index.get(child, -1)}
            if option["child"] < 0:
                option["end"] = "hand over" if action == "f" else "flop"
            options.append(option)
        nodes.append({"actor": int(tree.actor[node]), "pot": float(sum(state.committed)),
                      "behind": [0.0, 0.0], "to_call": float(max(state.street_put) - state.street_put[state.actor]),
                      "options": options})
    return nodes, order


def _state(tree: PublicTree, node: int) -> BettingState:
    state = BettingState.new(tree.rules)
    for action in tree.histories[node]:
        state = state.apply(action)
    return state


def strategy_bytes(trainer: Trainer, order: list[int], classes: int) -> bytes:
    blobs = []
    for node in order:
        legal = [s for s in range(3) if trainer.tree.children[node, s] >= 0]
        rows = np.zeros((classes, 3), dtype=np.uint8)
        for c in range(classes):
            policy = trainer.average_policy(node, c)
            rows[c, :len(legal)] = np.round(policy[legal] * 255).astype(np.uint8)
        blobs.append(rows.tobytes())
    return b"".join(blobs)


def export(trainer: Trainer, abstraction: Abstraction, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    classes = len(abstraction.preflop_names)
    nodes, order = preflop_nodes(trainer.tree)
    rules = trainer.tree.rules
    data = {"name": "hu", "label": "Heads-up FL O8",
            "detail": f"Heads-up · fixed limit · cap {rules.cap} bets · blinds {rules.small_blind:g}/{rules.big_blind:g} · chip EV",
            "iterations": trainer.iterations, "buckets": classes, "seats": ["BTN", "BB"], "nodes": nodes,
            "strategy": base64.b64encode(strategy_bytes(trainer, order, classes)).decode()}
    (out / "o8-hu.json").write_text(json.dumps(data, separators=(",", ":")))
    rows = []
    for c, name in enumerate(abstraction.preflop_names):
        suits = collections.Counter(name[1::2])
        rows.append([name, SHAPES[tuple(sorted(suits.values(), reverse=True))], int(abstraction.preflop_weights[c]),
                     c, low_group(name)])
    (out / "o8-classes.json").write_text(json.dumps({"tiers": list(GROUPS), "rows": rows}, separators=(",", ":")))
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, default=Path("tmp/o8_fl/run1"))
    parser.add_argument("--out", type=Path, default=Path("public/static"))
    parser.add_argument("--cap", type=int, default=5)
    parser.add_argument("--abstraction", type=Path, default=ABSTRACTION)
    parser.add_argument("--pool", type=Path, help="the DealPool the run was trained on, if any")
    args = parser.parse_args(argv)
    abstraction = Abstraction.cached(args.abstraction)
    pool = DealPool.load(args.pool) if args.pool else None
    trainer = Trainer.load(args.run / "checkpoint.npz", PublicTree.build(Rules(cap=args.cap)), abstraction, pool)
    data = export(trainer, abstraction, args.out)
    print(json.dumps({"iterations": data["iterations"], "nodes": len(data["nodes"]), "out": str(args.out)}))


if __name__ == "__main__":
    main()
