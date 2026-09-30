"""Global all-Trash SB range-deviation symmetry witness."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from .plan import EARLIER_POSITIONS
from .provenance import provenance_snapshot
from .runner import atomic_write_json
from .sampling import TierProvider
from .statistics import surrogate_hoeffding_bound
from .tiers import TierLookup

POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB", "BB")


@dataclass(frozen=True)
class MarginalCutoff:
    position: str
    marginal_enters: frozenset[str]

    @property
    def name(self) -> str:
        return f"marginal_enters_{self.position.lower()}_and_later"

    def folds(self, position: str, tier: str) -> bool:
        if tier == "Trash":
            return True
        if tier in ("Premium", "Speculative"):
            return False
        if tier == "Marginal":
            return position not in self.marginal_enters
        raise ValueError(f"unknown tier: {tier}")

    def fold_condition(self) -> dict[str, str]:
        return {
            position: (
                "Trash only"
                if position in self.marginal_enters
                else "Trash or Marginal"
            )
            for position in EARLIER_POSITIONS
        }


GLOBAL_CUTOFFS = tuple(
    MarginalCutoff(position, frozenset(POSITIONS[index:5]))
    for index, position in enumerate(POSITIONS[:5])
)


def _global_seed(user_seed: int, phase: str) -> int:
    material = json.dumps(
        ["plo-thesis-global-symmetry-integrated-v2", user_seed, phase],
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


@dataclass(frozen=True)
class GlobalPlan:
    phase: str
    user_seed: int
    deals: int
    cutoffs: tuple[MarginalCutoff, ...]
    simultaneous_cells: int
    seed: int
    status: str = "planned"


def freeze_global_plan(
    *, seed: int, phase: str, pilot_deals: int = 20_000
) -> GlobalPlan:
    if phase not in {"pilot", "main"}:
        raise ValueError("phase must be pilot or main")
    if pilot_deals <= 0:
        raise ValueError("pilot_deals must be positive")
    deals = pilot_deals if phase == "pilot" else 1_000_000
    return GlobalPlan(
        phase=phase,
        user_seed=seed,
        deals=deals,
        cutoffs=GLOBAL_CUTOFFS,
        simultaneous_cells=len(GLOBAL_CUTOFFS),
        seed=_global_seed(seed, phase),
    )


def global_symmetry_value(*, d_event: bool, bb_trash: bool) -> float:
    """Return Y=I(F & SB Trash)*(I(BB Trash)-0.5), in [-0.5, 0.5]."""
    if not d_event:
        return 0.0
    return 0.5 if bb_trash else -0.5


@dataclass(frozen=True)
class GlobalCellResult:
    cutoff: str
    prior_fold_condition: dict[str, str]
    deals_completed: int
    fourfold_count: int
    fourfold_percent: float
    sb_trash_count: int
    bb_trash_count: int
    d_event_count: int
    d_event_percent: float
    d_and_bb_trash_count: int
    bb_trash_given_d_percent: float
    trash_vs_trash_equity_percent_analytical: float
    equity_basis: str
    mean_y_bb_per_initial_deal: float


@dataclass(frozen=True)
class GlobalWitnessResult:
    phase: str
    seed: int
    deals_target: int
    deals_completed: int
    cells: tuple[GlobalCellResult, ...]
    complete: bool
    stop_reason: str | None
    elapsed_seconds: float = field(compare=False)

    def has_positive_empirical_mean_diagnostic(self) -> bool:
        """Descriptive only; this is not an inferential witness on pilot/partial data."""
        return any(cell.mean_y_bb_per_initial_deal > 0 for cell in self.cells)

    @classmethod
    def synthetic_for_test(cls, *, mean_surrogate_bb: float) -> GlobalWitnessResult:
        cell = GlobalCellResult(
            cutoff="synthetic",
            prior_fold_condition={},
            deals_completed=1,
            fourfold_count=1,
            fourfold_percent=100.0,
            sb_trash_count=1,
            bb_trash_count=1,
            d_event_count=1,
            d_event_percent=100.0,
            d_and_bb_trash_count=1,
            bb_trash_given_d_percent=100.0,
            trash_vs_trash_equity_percent_analytical=50.0,
            equity_basis="SB/BB exchangeability, including ties",
            mean_y_bb_per_initial_deal=mean_surrogate_bb,
        )
        return cls("test", 0, 1, 1, (cell,), True, None, 0.0)


def _deal(rng: random.Random) -> tuple[tuple[int, ...], ...]:
    cards = rng.sample(range(52), 24)
    holes = tuple(tuple(cards[4 * seat:4 * seat + 4]) for seat in range(6))
    return holes


def sample_global_witness(
    plan: GlobalPlan,
    *,
    lookup: TierProvider,
    max_deals: int | None = None,
    max_seconds: float | None = None,
) -> GlobalWitnessResult:
    rng = random.Random(plan.seed)
    started = time.perf_counter()
    completed = 0
    fourfolds = [0] * len(plan.cutoffs)
    sb_trash_count = 0
    bb_trash_count = 0
    d_events = [0] * len(plan.cutoffs)
    d_and_bb_trash = [0] * len(plan.cutoffs)
    y_sums = [0.0] * len(plan.cutoffs)
    stop_reason = None
    while completed < plan.deals:
        if max_deals is not None and completed >= max_deals:
            stop_reason = "max_deals"
            break
        if max_seconds is not None and time.perf_counter() - started >= max_seconds:
            stop_reason = "max_seconds"
            break
        holes = _deal(rng)
        tiers = tuple(lookup.tier(hole) for hole in holes)
        completed += 1
        sb_trash = tiers[4] == "Trash"
        bb_trash = tiers[5] == "Trash"
        sb_trash_count += int(sb_trash)
        bb_trash_count += int(bb_trash)
        fold_events = [
            all(
                cutoff.folds(position, tiers[index])
                for index, position in enumerate(EARLIER_POSITIONS)
            )
            for cutoff in plan.cutoffs
        ]
        for index, fourfold in enumerate(fold_events):
            fourfolds[index] += int(fourfold)
            d_event = fourfold and sb_trash
            d_events[index] += int(d_event)
            d_and_bb_trash[index] += int(d_event and bb_trash)
            y_sums[index] += global_symmetry_value(
                d_event=d_event, bb_trash=bb_trash
            )
    elapsed = time.perf_counter() - started
    cells = tuple(
        GlobalCellResult(
            cutoff=cutoff.position,
            prior_fold_condition=cutoff.fold_condition(),
            deals_completed=completed,
            fourfold_count=fourfolds[index],
            fourfold_percent=(
                100 * fourfolds[index] / completed if completed else 0.0
            ),
            sb_trash_count=sb_trash_count,
            bb_trash_count=bb_trash_count,
            d_event_count=d_events[index],
            d_event_percent=(
                100 * d_events[index] / completed if completed else 0.0
            ),
            d_and_bb_trash_count=d_and_bb_trash[index],
            bb_trash_given_d_percent=(
                100 * d_and_bb_trash[index] / d_events[index]
                if d_events[index]
                else 0.0
            ),
            trash_vs_trash_equity_percent_analytical=50.0,
            equity_basis=(
                "analytical SB/BB exchangeability conditional on F and both Trash; "
                "ties included; no boards sampled"
            ),
            mean_y_bb_per_initial_deal=(
                y_sums[index] / completed if completed else 0.0
            ),
        )
        for index, cutoff in enumerate(plan.cutoffs)
    )
    return GlobalWitnessResult(
        phase=plan.phase,
        seed=plan.seed,
        deals_target=plan.deals,
        deals_completed=completed,
        cells=cells,
        complete=completed == plan.deals,
        stop_reason=stop_reason,
        elapsed_seconds=elapsed,
    )


def _base_global_report(plan: GlobalPlan) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "planned",
        "scope": (
            "global SB all-Trash range-deviation symmetry witness; not a global "
            "equilibrium or exploitability certificate"
        ),
        "provenance": provenance_snapshot(),
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
            "full_thesis": {
                "Trash": "always folds voluntarily; BB Trash free-checks",
                "Premium_Speculative": (
                    "always continue first-in and always continue versus a 3-bet"
                ),
                "Marginal": (
                    "first-in action follows the declared position cutoff; folds versus a 3-bet"
                ),
            },
        },
        "mathematical_witness": (
            "Let F be four prior folds, S be SB Trash, and B be BB Trash. "
            "SB/BB exchangeability conditional on F and both hands Trash gives "
            "E[1{F&S&B}*showdown_share]=0.5*P(F&S&B), including ties. Therefore "
            "the true unconditional all-Trash SB limp/fold deviation gain is at "
            "least E[Y], where Y=1{F&S}*(1{B}-0.5). This is an expectation-level "
            "bound, not a pointwise payoff bound; no board sampling is used."
        ),
        "sample_range_bb": [-0.5, 0.5],
        "units": "BB per initially dealt hand for the SB player; not conditional on acting",
        "policy_robustness": (
            "Nonfold actions by the first four seats are arbitrary. The witness is "
            "valid for every non-Trash BB check/raise mix and is independent of all "
            "versus-3-bet action mixing."
        ),
        "confidence": (
            "K=5, alpha=0.05. The confirmatory lower bound is one-sided and uses "
            "log(K/alpha). The separately labeled two-sided surrogate interval uses "
            "log(2K/alpha). The upper endpoint bounds E[Y] only, not actual gain. "
            "A zero or negative lower bound is inconclusive."
        ),
        "decision_rules": {
            "positive_lower_bound": (
                "rejects exact equilibrium within the tested Marginal-mask family"
            ),
            "lower_bound_above_0_015_bb": (
                "rejects the requested 0.015 BB threshold for every non-Trash BB action mix"
            ),
        },
        "estimator_id": "symmetry-integrated-y-v2-no-board",
        "phase": plan.phase,
        "stream_role": (
            "independent confirmatory fixed plan"
            if plan.phase == "main"
            else "cost/discovery pilot; not confirmatory evidence"
        ),
        "user_seed": plan.user_seed,
        "rng_seed": plan.seed,
        "iid_deals_target": plan.deals,
        "simultaneous_cells_k": plan.simultaneous_cells,
        "fixed_plan_frozen_before_sampling": True,
        "planned_cells": [
            {
                "marginal_cutoff": cutoff.position,
                "prior_fold_condition": cutoff.fold_condition(),
                "deals_target": plan.deals,
            }
            for cutoff in plan.cutoffs
        ],
        "cells": [],
    }


def run_global_audit(
    plan: GlobalPlan,
    *,
    output: Path,
    max_deals: int | None = None,
    max_seconds: float | None = None,
) -> dict[str, object]:
    report = _base_global_report(plan)
    report["guards"] = {
        "max_deals": max_deals,
        "max_sampling_seconds": max_seconds,
        "partial_results_have_no_inferential_bounds": True,
    }
    atomic_write_json(output, report)
    lookup = TierLookup.build()
    result = sample_global_witness(
        plan,
        lookup=lookup,
        max_deals=max_deals,
        max_seconds=max_seconds,
    )
    rows = []
    positive_lower_bound = False
    threshold_rejected = False
    for cell in result.cells:
        row = dataclasses.asdict(cell)
        inference = None
        if result.complete:
            bound = surrogate_hoeffding_bound(
                mean_surrogate_bb=cell.mean_y_bb_per_initial_deal,
                samples=result.deals_completed,
                cells=plan.simultaneous_cells,
                sample_lower_bb=-0.5,
                sample_upper_bb=0.5,
            )
            inference = dataclasses.asdict(bound)
            cell_positive = bound.lower_true_deviation_gain_bb > 0
            cell_above_threshold = bound.lower_true_deviation_gain_bb > 0.015
            inference["positive_one_sided_lower_bound"] = cell_positive
            inference["lower_bound_exceeds_0_015_bb"] = cell_above_threshold
            inference["confirmatory_exact_equilibrium_rejected"] = (
                plan.phase == "main" and cell_positive
            )
            inference["confirmatory_threshold_0_015_rejected"] = (
                plan.phase == "main" and cell_above_threshold
            )
            positive_lower_bound = positive_lower_bound or cell_positive
            threshold_rejected = threshold_rejected or cell_above_threshold
        row["inference"] = inference
        rows.append(row)
    report.update(
        {
            "status": "complete" if result.complete else "partial",
            "tier_lookup": {
                "physical_hands": len(lookup),
                "suit_isomorphism_classifier_calls": lookup.classifier_calls,
                "build_seconds": lookup.build_seconds,
            },
            "deals_completed": result.deals_completed,
            "sampling_elapsed_seconds": result.elapsed_seconds,
            "stop_reason": result.stop_reason,
            "confirmatory_witness_established": (
                result.complete and plan.phase == "main" and positive_lower_bound
            ),
            "confirmatory_threshold_0_015_rejected": (
                result.complete and plan.phase == "main" and threshold_rejected
            ),
            "cells": rows,
        }
    )
    if plan.phase == "pilot" and result.deals_completed:
        projected_sampling = result.elapsed_seconds * 1_000_000 / result.deals_completed
        projected_total = projected_sampling + lookup.build_seconds
        report["projected_global_main_sampling_seconds"] = projected_sampling
        report["projected_global_main_total_seconds"] = projected_total
        report["recommended_global_main_budget_seconds"] = 30 * math.ceil(
            1.5 * projected_total / 30
        )
    atomic_write_json(output, report)
    return report
