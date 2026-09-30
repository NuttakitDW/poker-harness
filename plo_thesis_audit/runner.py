"""Durable audit orchestration and self-describing JSON reporting."""

from __future__ import annotations

import dataclasses
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .plan import SamplePlan
from .provenance import own_source_hash, provenance_snapshot
from .sampling import CellResult, sample_cell
from .statistics import hoeffding_bound
from .tiers import TierLookup


def source_hash() -> str:
    return own_source_hash()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def report_is_complete(
    results: list[CellResult], *, expected_cells: int, accepted_per_cell: int
) -> bool:
    return (
        len(results) == expected_cells
        and all(result.complete and result.accepted == accepted_per_cell for result in results)
    )


def _candidate_row(candidate: Any) -> dict[str, Any]:
    return {
        "text": candidate.text,
        "cards": list(candidate.hand),
        "tier": candidate.tier,
    }


def _cell_row(result: CellResult, *, cells: int) -> dict[str, Any]:
    row = dataclasses.asdict(result)
    if result.complete:
        bound = hoeffding_bound(
            mean_x=result.mean_x,
            accepted=result.accepted,
            cells=cells,
            alpha=0.05,
        )
        row["simultaneous_hoeffding"] = dataclasses.asdict(bound)
    else:
        row["simultaneous_hoeffding"] = None
    return row


def _base_report(plan: SamplePlan) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "planned",
        "source_hash": source_hash(),
        "provenance": provenance_snapshot(),
        "scope": "conditional direct hypothesis test; not a global equilibrium or exploitability certificate",
        "assumptions": {
            "variant": "PLO4 high, exactly two hole plus three board cards",
            "format": "tournament chip EV",
            "table": "six-max",
            "effective_stack_bb": 100.0,
            "blinds_bb": [0.5, 1.0],
            "ante_bb": 0.0,
            "rake": 0.0,
            "tournament_payouts_or_icm": False,
            "preflop": "maximum pot open, maximum pot 3-bet, then call or fold (C/F)",
            "postflop": "forced checkdown",
            "baseline_ev_fold_bb": -0.5,
        },
        "authorship": {
            "tier_classifier": "existing Hwang-inspired project helper",
            "marginal_scenarios": "authored test instantiations, not exact Hwang prescriptions or universal marginal policies",
        },
        "conditioning": "UTG, HJ, CO, BTN hands are physically dealt without replacement after fixing hero; retain only deals where all four fold under the declared scenario",
        "estimand": "delta >= 2*E[1{BB Trash}*hero showdown share | exact hero hand, four prior folds] - 0.5 BB",
        "bb_policy_robustness": (
            "Trash BB must take its free check (which is not VPIP); every non-Trash "
            "BB action policy is covered because its contribution is conservatively "
            "lower-bounded by -0.5 BB"
        ),
        "inference": (
            "fixed-n one-sided Hoeffding lower bound with radius sqrt(log(K/alpha)/(2n)); "
            "K is all preregistered valid cells, X is in [0,1], and alpha is "
            "0.05 familywide. The separately reported two-sided surrogate interval "
            "uses log(2K/alpha). No upper endpoint is an upper bound on true gain"
        ),
        "phase": plan.phase,
        "user_seed": plan.user_seed,
        "rng_separation": "SHA-256 domain seeds by phase, exact candidate, and scenario",
        "stream_roles": {
            "pilot": "cost/discovery statistics only",
            "main": "independent fixed-manifest holdout stream",
            "adaptive_selection_on_main": False,
        },
        "accepted_per_cell": plan.accepted_per_cell,
        "simultaneous_cells_k": plan.simultaneous_cells,
        "valid_candidates": [_candidate_row(row) for row in plan.valid_candidates],
        "discarded_nontrash_candidates": [_candidate_row(row) for row in plan.discarded_candidates],
        "scenario_names": [cell.scenario.name for cell in plan.cells[:3]],
        "candidate_manifest_frozen_before_sampling": True,
        "planned_cells": [
            {
                "candidate_text": cell.candidate_text,
                "hero_cards": list(cell.hero_hand),
                "hero_tier": cell.hero_tier,
                "scenario": cell.scenario.name,
                "prior_fold_condition": cell.scenario.fold_condition(),
                "seed": cell.seed,
                "accepted_target": plan.accepted_per_cell,
            }
            for cell in plan.cells
        ],
        "cells": [],
    }


def run_audit(
    plan: SamplePlan,
    *,
    output: Path,
    max_draws_per_cell: int | None = None,
    max_seconds: float | None = None,
) -> dict[str, Any]:
    report = _base_report(plan)
    report["guards"] = {
        "max_draws_per_cell": max_draws_per_cell,
        "max_sampling_seconds_total": max_seconds,
        "guarded_results_may_be_partial": True,
    }
    atomic_write_json(output, report)
    lookup = TierLookup.build()
    report["tier_lookup"] = {
        "physical_hands": len(lookup),
        "suit_isomorphism_classifier_calls": lookup.classifier_calls,
        "build_seconds": lookup.build_seconds,
    }
    results: list[CellResult] = []
    started = time.perf_counter()
    for cell in plan.cells:
        remaining = None
        if max_seconds is not None:
            remaining = max(0.0, max_seconds - (time.perf_counter() - started))
        result = sample_cell(
            cell,
            accepted_target=plan.accepted_per_cell,
            lookup=lookup,
            max_draws=max_draws_per_cell,
            max_seconds=remaining,
        )
        results.append(result)
        report["cells"] = [
            _cell_row(row, cells=plan.simultaneous_cells) for row in results
        ]
        report["status"] = "running" if result.complete else "partial"
        atomic_write_json(output, report)
        if not result.complete:
            break
    elapsed = time.perf_counter() - started
    complete = report_is_complete(
        results,
        expected_cells=plan.simultaneous_cells,
        accepted_per_cell=plan.accepted_per_cell,
    )
    report["status"] = "complete" if complete else "partial"
    report["sampling_elapsed_seconds"] = elapsed
    report["accepted_total"] = sum(row.accepted for row in results)
    report["candidate_draws_total"] = sum(row.candidate_draws for row in results)
    if plan.phase == "pilot" and report["accepted_total"]:
        main_accepted = plan.simultaneous_cells * 50_000
        projected_sampling = elapsed * main_accepted / report["accepted_total"]
        projected_total = projected_sampling + lookup.build_seconds
        report["projected_main_sampling_seconds"] = projected_sampling
        report["projected_main_total_seconds"] = projected_total
        report["recommended_main_budget_seconds"] = 30 * math.ceil(
            1.5 * projected_total / 30
        )
        report["main_requires_budget_confirmation"] = projected_total > 300
    atomic_write_json(output, report)
    return report
