"""Command-line entry point for the preregistered pilot and main audits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .global_witness import freeze_global_plan, run_global_audit
from .plan import freeze_plan
from .runner import run_audit


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m plo_thesis_audit")
    result.add_argument(
        "phase", choices=("pilot", "main", "global-pilot", "global-main")
    )
    result.add_argument("--seed", type=int, default=20260929)
    result.add_argument("--output", type=Path)
    result.add_argument("--max-draws-per-cell", type=int)
    result.add_argument("--max-deals", type=int)
    result.add_argument("--max-seconds", type=float)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    output = args.output or Path("tmp/plo_chipev/thesis-work") / f"{args.phase}.json"
    if args.phase.startswith("global-"):
        global_phase = args.phase.removeprefix("global-")
        global_plan = freeze_global_plan(seed=args.seed, phase=global_phase)
        global_report = run_global_audit(
            global_plan,
            output=output,
            max_deals=args.max_deals,
            max_seconds=args.max_seconds,
        )
        global_summary = {
            "status": global_report["status"],
            "output": str(output),
            "deals_completed": global_report["deals_completed"],
            "sampling_elapsed_seconds": global_report["sampling_elapsed_seconds"],
            "projected_global_main_total_seconds": global_report.get(
                "projected_global_main_total_seconds"
            ),
            "recommended_global_main_budget_seconds": global_report.get(
                "recommended_global_main_budget_seconds"
            ),
        }
        print(json.dumps(global_summary, sort_keys=True))
        return 0 if global_report["status"] == "complete" else 2
    plan = freeze_plan(seed=args.seed, phase=args.phase)
    report = run_audit(
        plan,
        output=output,
        max_draws_per_cell=args.max_draws_per_cell,
        max_seconds=args.max_seconds,
    )
    summary = {
        "status": report["status"],
        "output": str(output),
        "accepted_total": report["accepted_total"],
        "candidate_draws_total": report["candidate_draws_total"],
        "sampling_elapsed_seconds": report["sampling_elapsed_seconds"],
        "projected_main_sampling_seconds": report.get("projected_main_sampling_seconds"),
        "projected_main_total_seconds": report.get("projected_main_total_seconds"),
        "recommended_main_budget_seconds": report.get("recommended_main_budget_seconds"),
        "main_requires_budget_confirmation": report.get("main_requires_budget_confirmation"),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if report["status"] == "complete" else 2
