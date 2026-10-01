"""CLI: ``python -m plo_premium_proof solve|verify|solve-full|verify-full|ft-solve|export-chart``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .fullsolve import FullSolveConfig, solve_full, verify_full
from .solve import SolveConfig, solve
from .tables import FIRST_IN_POSITIONS
from .verify import verify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m plo_premium_proof")
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("solve")
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--minutes", type=float, required=True)
    train.add_argument("--threads", type=int, default=12)
    train.add_argument("--seed", type=int, default=1)
    train.add_argument("--epoch-traversals", type=int, default=4_000_000)
    train.add_argument("--discount-epochs", type=int, default=100)
    train.add_argument("--checkpoint-every", type=int, default=25)

    check = commands.add_parser("verify")
    check.add_argument("--model", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--fit-samples", type=int, default=20_000)
    check.add_argument("--test-samples", type=int, default=20_000)
    check.add_argument("--threads", type=int, default=12)
    check.add_argument("--seed", type=int, default=7)
    check.add_argument("--positions", default=",".join(FIRST_IN_POSITIONS))
    check.add_argument("--limit", type=int)
    check.add_argument("--exploit-classes", type=int, default=0)
    check.add_argument("--tier", default="Premium")
    check.add_argument("--per-tier", type=int)
    full = commands.add_parser("solve-full")
    full.add_argument("--output", type=Path, required=True)
    full.add_argument("--minutes", type=float, required=True)
    full.add_argument("--stack", type=float, default=20.0)
    full.add_argument("--raise-caps", default="3,2,2,2", help="max raises per street, preflop first")
    full.add_argument("--float32", action="store_true", help="single-precision tables (large trees)")
    full.add_argument("--ante", type=float, default=0.0, help="per-player ante in bb (not in preflop pot size)")
    full.add_argument("--threads", type=int, default=12)
    full.add_argument("--seed", type=int, default=1)
    full.add_argument("--epoch-deals", type=int, default=200_000)
    full.add_argument("--discount-epochs", type=int, default=100)
    full.add_argument("--checkpoint-every", type=int, default=20)

    table = commands.add_parser("ft-solve", help="final-table ICM solve from a JSON table spec")
    table.add_argument("--spec", type=Path, required=True, help="FinalTableSpec as JSON")
    table.add_argument("--output", type=Path, required=True, help="folder for status.json and result.json")

    audit = commands.add_parser("verify-full")
    audit.add_argument("--model", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--samples", type=int, default=8_000)
    audit.add_argument("--threads", type=int, default=12)
    audit.add_argument("--seed", type=int, default=7)
    audit.add_argument("--positions", default=",".join(FIRST_IN_POSITIONS))
    audit.add_argument("--limit", type=int)
    audit.add_argument("--other-classes", type=int, default=0)
    audit.add_argument("--tier", default="Premium")
    audit.add_argument("--per-tier", type=int)
    audit.add_argument("--sampled", action="store_true", help="sample opponent paths (large trees)")
    export = commands.add_parser("export-chart", help="compact preflop chart from finished solves")
    export.add_argument("--name", required=True, help="chart name, e.g. 20bb or mtt40")
    export.add_argument("--models", type=Path, nargs="+", required=True)
    args = parser.parse_args(argv)

    if args.command == "export-chart":
        from .fulltree import FullTreeConfig
        from .preflop_chart import CHART_DIR, export_chart
        import numpy as _np
        with _np.load(args.models[0]) as data:
            meta = json.loads(str(data["meta"]))
        config = FullTreeConfig(stack_bb=meta["stack_bb"], raise_caps=tuple(meta["raise_caps"]),
                                ante_bb=meta.get("ante_bb", 0.0))
        deals = []
        for path in args.models:
            with _np.load(path) as data:
                deals.append(json.loads(str(data["meta"]))["deals"])
        out = export_chart(args.models, config, CHART_DIR / args.name,
                           {"name": args.name, "deals_per_seed": deals, "game": meta.get("game", "")})
        print(f"wrote chart {out}")
        return 0

    if args.command == "solve-full":
        config = FullSolveConfig(
            seconds=args.minutes * 60, stack_bb=args.stack, threads=args.threads, seed=args.seed,
            raise_caps=tuple(int(x) for x in args.raise_caps.split(",")), single_precision=args.float32,
            ante_bb=args.ante,
            epoch_deals=args.epoch_deals, discount_epochs=args.discount_epochs,
            checkpoint_every=args.checkpoint_every,
        )
        print(json.dumps(solve_full(config, args.output), indent=2))
        return 0
    if args.command == "ft-solve":
        from .finaltable import FinalTableSpec, solve as solve_table
        spec = FinalTableSpec.from_dict(json.loads(args.spec.read_text()))
        print(json.dumps(solve_table(spec, args.output), indent=1))
        return 0
    if args.command == "verify-full":
        positions = tuple(name.strip().upper() for name in args.positions.split(","))
        report = verify_full(args.model, samples=args.samples, threads=args.threads, seed=args.seed,
                             positions=positions, limit=args.limit, other_classes=args.other_classes,
                             tier=args.tier, per_tier=args.per_tier, sampled=args.sampled)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1))
        print(json.dumps(report["summary"], indent=1))
        return 0

    if args.command == "solve":
        config = SolveConfig(
            seconds=args.minutes * 60, threads=args.threads, seed=args.seed,
            epoch_traversals=args.epoch_traversals, discount_epochs=args.discount_epochs,
            checkpoint_every=args.checkpoint_every,
        )
        print(json.dumps(solve(config, args.output), indent=2))
        return 0
    positions = tuple(name.strip().upper() for name in args.positions.split(","))
    unknown = set(positions) - set(FIRST_IN_POSITIONS)
    if unknown:
        parser.error(f"unknown positions: {sorted(unknown)}")
    report = verify(
        args.model, fit_samples=args.fit_samples, test_samples=args.test_samples,
        threads=args.threads, seed=args.seed, positions=positions, limit=args.limit,
        exploit_classes=args.exploit_classes, tier=args.tier, per_tier=args.per_tier,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1))
    print(json.dumps(report["summary"], indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
