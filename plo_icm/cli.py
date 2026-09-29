"""Command-line interface for generating, solving, and inspecting custom spots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config, ConfigError, sunday_classic_mini
from .solver import Solver, UnseenInformationSet


def _json(value: object) -> None:
    print(json.dumps(value, indent=2))


def _preset(args: argparse.Namespace) -> int:
    cfg = sunday_classic_mini(players_remaining=args.players, stack=args.stack, ante=args.ante,
                              ante_mode=args.ante_mode, iterations=args.iterations, seed=args.seed,
                              time_limit=args.time_limit, max_nodes=args.max_nodes,
                              max_infosets=args.max_infosets,
                              opening_raise_mode=args.opening_raise_mode)
    text = json.dumps(cfg.to_dict(), indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


def _solve(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config JSON must be an object")
    solver = Solver(Config.from_dict(data))
    metadata = solver.train()
    solver.save(args.output)
    _json(metadata)
    return 0


def _query(args: argparse.Namespace) -> int:
    solver = Solver.load(args.model)
    _json({"metadata": solver.metadata(), "seat": args.seat, "hand": args.hand, "board": args.board,
           "results": solver.query(args.seat, args.hand, args.board)})
    return 0


def _export(args: argparse.Namespace) -> int:
    solver = Solver.load(args.model)
    rows = []
    for key, info in solver.infosets.items():
        state = json.loads(key)
        if state[1] == 0 and info.visits > 0 and info.strategy_sum.sum() > 0:
            rows.append({"seat": state[0], "hand": state[2], "history": state[4],
                         "actions": list(info.actions), "strategy": info.average().tolist(),
                         "support": info.visits, "average_weight": float(info.strategy_sum.sum())})
    rows.sort(key=lambda r: (r["seat"], r["hand"], r["history"]))
    payload = {"metadata": solver.metadata(), "warning": "Sparse visited exact-card states; not a complete chart",
               "preflop": rows}
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m plo_icm")
    sub = p.add_subparsers(dest="command", required=True)
    preset = sub.add_parser("preset", help="write the Sunday Classic Mini example configuration")
    preset.add_argument("-o", "--output")
    preset.add_argument("--players", type=int, default=76)
    preset.add_argument("--stack", type=float, default=10)
    preset.add_argument("--ante", type=float, default=.1,
                        help="confirmed example ante in bb; custom configs must always specify it")
    preset.add_argument("--ante-mode", choices=("individual", "bb"), default="individual")
    preset.add_argument("--iterations", type=int, default=1000)
    preset.add_argument("--seed", type=int, default=1)
    preset.add_argument("--time-limit", type=float)
    preset.add_argument("--max-nodes", type=int, default=100_000)
    preset.add_argument("--max-infosets", type=int, default=50_000)
    preset.add_argument("--opening-raise-mode", choices=("two_bb_only", "pot_only", "both"),
                        default="two_bb_only")
    preset.set_defaults(func=_preset)
    solve = sub.add_parser("solve")
    solve.add_argument("config")
    solve.add_argument("-o", "--output", required=True)
    solve.set_defaults(func=_solve)
    query = sub.add_parser("query")
    query.add_argument("model")
    query.add_argument("--seat", type=int, required=True, choices=range(6))
    query.add_argument("--hand", required=True)
    query.add_argument("--board", default="")
    query.set_defaults(func=_query)
    export = sub.add_parser("export")
    export.add_argument("model")
    export.add_argument("-o", "--output")
    export.set_defaults(func=_export)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return args.func(args)
    except (ConfigError, ValueError, UnseenInformationSet, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
