"""Train the heads-up FL O8 solver and read its preflop strategy.

    .venv/bin/python -m o8_fl train --iterations 1000000000 --threads 14 --run tmp/o8_fl/run1
    .venv/bin/python -m o8_fl chart --run tmp/o8_fl/run1
    .venv/bin/python -m o8_fl query AsAh3s2h --run tmp/o8_fl/run1
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from .buckets import Abstraction
from .cards import card_ids
from .game import Rules
from .trainer import Trainer
from .tree import PublicTree

ABSTRACTION = Path("tmp/o8_fl/abstraction.npz")
# Preflop spots: (label, history, action names for slots fold, check/call, bet/raise)
SPOTS = (
    ("sb_open", "", ("fold", "limp", "raise")),
    ("bb_vs_limp", "c", ("-", "check", "raise")),
    ("bb_vs_raise", "r", ("fold", "call", "3bet")),
    ("sb_vs_3bet", "rr", ("fold", "call", "4bet")),
)


def _load(run: Path, cap: int, abstraction_path: Path = ABSTRACTION) -> tuple[Trainer, Abstraction]:
    abstraction = Abstraction.cached(abstraction_path)
    tree = PublicTree.build(Rules(cap=cap))
    checkpoint = run / "checkpoint.npz"
    trainer = Trainer.load(checkpoint, tree, abstraction) if checkpoint.exists() else Trainer(tree, abstraction)
    return trainer, abstraction


def spot_table(trainer: Trainer, abstraction: Abstraction) -> dict[str, np.ndarray]:
    """Average policy for every preflop class at each spot: {label: (classes, 3)}."""
    out = {}
    for label, history, _ in SPOTS:
        node = trainer.tree.history_to_node[history]
        out[label] = np.array([trainer.average_policy(node, c) for c in range(len(abstraction.preflop_names))])
    return out


def summary(trainer: Trainer, abstraction: Abstraction) -> dict[str, dict[str, float]]:
    """Frequency of each action over the hands that reach the spot, weighted by how often they reach it."""
    table = spot_table(trainer, abstraction)
    out = {}
    for label, history, names in SPOTS:
        node = trainer.tree.history_to_node[history]
        reach = np.array([trainer.visits(node, c) for c in range(len(abstraction.preflop_names))])
        weights = reach / reach.sum() if reach.sum() > 0 else abstraction.preflop_weights / abstraction.preflop_weights.sum()
        out[label] = {name: round(float(weights @ table[label][:, s]), 4) for s, name in enumerate(names) if name != "-"}
    return out


def train(args: argparse.Namespace) -> None:
    run = Path(args.run)
    run.mkdir(parents=True, exist_ok=True)
    trainer, abstraction = _load(run, args.cap, Path(args.abstraction))
    target = trainer.iterations + args.iterations
    previous = None
    # Trainer.run rounds each chunk down to a multiple of the thread count; stop once less than that is left.
    while target - trainer.iterations >= args.threads:
        chunk = min(args.checkpoint_every, target - trainer.iterations)
        speed = trainer.run(chunk, threads=args.threads, seed=args.seed + trainer.iterations)
        trainer.save(run / "checkpoint.npz")
        root = spot_table(trainer, abstraction)["sb_open"]
        change = None if previous is None else float(np.abs(root - previous).sum(axis=1).mean())
        previous = root
        line = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "iterations": trainer.iterations,
                "per_second": round(speed), "root_change": change, "summary": summary(trainer, abstraction)}
        with open(run / "progress.jsonl", "a") as log:
            log.write(json.dumps(line) + "\n")
        print(json.dumps(line), flush=True)


def chart(args: argparse.Namespace) -> None:
    trainer, abstraction = _load(Path(args.run), args.cap, Path(args.abstraction))
    table = spot_table(trainer, abstraction)
    out = Path(args.out or Path(args.run) / "preflop.csv")
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["hand", "combos"] + [f"{label}_{name}" for label, _, names in SPOTS for name in names if name != "-"]
        writer.writerow(header)
        for c, name in enumerate(abstraction.preflop_names):
            row = [name, int(abstraction.preflop_weights[c])]
            for label, _, names in SPOTS:
                row += [round(float(table[label][c, s]), 4) for s, n in enumerate(names) if n != "-"]
            writer.writerow(row)
    print(json.dumps({"iterations": trainer.iterations, "csv": str(out), "summary": summary(trainer, abstraction)}))


def query(args: argparse.Namespace) -> None:
    trainer, abstraction = _load(Path(args.run), args.cap, Path(args.abstraction))
    cls = abstraction.preflop_class(card_ids(args.hand))
    table = spot_table(trainer, abstraction)
    result = {"hand": abstraction.preflop_names[cls], "iterations": trainer.iterations}
    for label, _, names in SPOTS:
        result[label] = {n: round(float(table[label][cls, s]), 3) for s, n in enumerate(names) if n != "-"}
    print(json.dumps(result, indent=1))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="o8_fl", description=__doc__.splitlines()[0])
    parser.add_argument("--run", default="tmp/o8_fl/run1")
    parser.add_argument("--cap", type=int, default=5)
    parser.add_argument("--abstraction", default=str(ABSTRACTION))
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--iterations", type=int, required=True)
    t.add_argument("--threads", type=int, default=14)
    t.add_argument("--checkpoint-every", type=int, default=50_000_000)
    t.add_argument("--seed", type=int, default=1)
    c = sub.add_parser("chart")
    c.add_argument("--out")
    q = sub.add_parser("query")
    q.add_argument("hand")
    args = parser.parse_args(argv)
    {"train": train, "chart": chart, "query": query}[args.command](args)
