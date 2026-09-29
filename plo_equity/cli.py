"""Build, export and query approximate PLO4 showdown equity versus random hands."""

from __future__ import annotations

import argparse
import json
import os
import pathlib

from .builder import build
from .cache import Cache, Metadata
from .cards import canonical_hand, card_text, class_key, parse_hand
from .simulation import TrialStats
from .table import export_tables, ranked_classes, weighted_summary

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "tmp" / "plo_equity.sqlite"
DEFAULT_CLASS_CSV = ROOT / "tmp" / "plo_equity_classes.csv"
DEFAULT_PHYSICAL_CSV = ROOT / "tmp" / "plo_equity_physical.csv"
DEFAULT_SEED = 20260929


def _add_common(command: argparse.ArgumentParser) -> None:
    command.add_argument("--cache", type=pathlib.Path, default=DEFAULT_CACHE)
    command.add_argument("--seed", type=int, default=DEFAULT_SEED)
    command.add_argument("--opponents", type=int, default=1)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build_command = commands.add_parser("build")
    _add_common(build_command)
    build_command.add_argument("--samples", type=int, default=100_000)
    build_command.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    build_command.add_argument("--class-csv", type=pathlib.Path, default=DEFAULT_CLASS_CSV)
    build_command.add_argument("--physical-csv", type=pathlib.Path, default=DEFAULT_PHYSICAL_CSV)
    build_command.add_argument("--no-export", action="store_true")
    export_command = commands.add_parser("export")
    _add_common(export_command)
    export_command.add_argument("--class-csv", type=pathlib.Path, default=DEFAULT_CLASS_CSV)
    export_command.add_argument("--physical-csv", type=pathlib.Path, default=DEFAULT_PHYSICAL_CSV)
    query = commands.add_parser("query")
    _add_common(query)
    query.add_argument("hand", help="four exact physical cards, e.g. AsAhKsKh")
    return result


def _load(args: argparse.Namespace) -> dict[str, TrialStats]:
    with Cache(args.cache, Metadata(args.seed, args.opponents)) as cache:
        return cache.load()


def _progress(done: int, total: int, elapsed: float) -> None:
    if done == total or done % 100 == 0:
        rate = done / elapsed if elapsed else 0
        remaining = (total - done) / rate if rate else 0
        print(f"{done:,}/{total:,} classes, {elapsed:.1f}s elapsed, ETA {remaining:.1f}s", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "build":
        metadata = Metadata(args.seed, args.opponents)
        result = build(args.cache, args.samples, args.seed, args.opponents, args.workers,
                       progress=_progress)
        rows = _load(args)
        payload = {**result.__dict__, **weighted_summary(rows)}
        if not args.no_export:
            export_tables(rows, args.class_csv, args.physical_csv, metadata)
            payload.update({"class_csv": str(args.class_csv), "physical_csv": str(args.physical_csv)})
        print(json.dumps(payload, indent=2))
        return 0
    rows = _load(args)
    if args.command == "export":
        export_tables(rows, args.class_csv, args.physical_csv, Metadata(args.seed, args.opponents))
        print(json.dumps({**weighted_summary(rows), "class_csv": str(args.class_csv),
                          "physical_csv": str(args.physical_csv)}, indent=2))
        return 0
    hand = canonical_hand(parse_hand(args.hand))
    key = class_key(hand)
    stats = rows.get(key)
    if stats is None:
        raise SystemExit("this suit class has not been sampled")
    payload = {"requested_hand": args.hand, "class_representative": card_text(hand),
               "class_key": key, "samples": stats.n, "equity": stats.equity,
               "standard_error": stats.standard_error, "win_rate": stats.win_rate,
               "tie_rate": stats.tie_rate, "opponents": args.opponents,
               "opponent_range": "uniform random physical PLO4 hand(s)"}
    payload.update({
        "equity_ci95_low": max(0.0, stats.equity - 1.96 * stats.standard_error),
        "equity_ci95_high": min(1.0, stats.equity + 1.96 * stats.standard_error),
    })
    if len(rows) == 16_432:
        ranked = {row["class_key"]: row for row in ranked_classes(rows)}[key]
        payload.update({name: ranked[name] for name in (
            "estimated_class_rank", "estimated_physical_rank_start",
            "estimated_physical_rank_end", "physical_weighted_percentile", "rank_label")})
    print(json.dumps(payload, indent=2))
    return 0
