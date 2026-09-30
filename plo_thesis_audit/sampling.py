"""Exact rejection sampler conditional on the four prior thesis folds."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Protocol

from .cards import full_deal
from .evaluator import showdown_share
from .plan import EARLIER_POSITIONS, Cell, Scenario


class TierProvider(Protocol):
    def tier(self, hand: tuple[int, ...]) -> str: ...


def earlier_four_fold(
    holes: tuple[tuple[int, ...], ...], scenario: Scenario, lookup: TierProvider
) -> bool:
    if len(holes) != 4:
        raise ValueError("conditioning requires four earlier hands")
    return all(
        scenario.folds(position, lookup.tier(hole))
        for position, hole in zip(EARLIER_POSITIONS, holes, strict=True)
    )


@dataclass(frozen=True)
class CellResult:
    candidate_text: str
    hero_cards: tuple[int, int, int, int]
    hero_tier: str
    scenario: str
    prior_fold_condition: dict[str, str]
    seed: int
    accepted_target: int
    accepted: int
    candidate_draws: int
    acceptance_percent: float
    bb_trash_count: int
    bb_trash_percent: float
    equity_vs_bb_trash_percent: float | None
    mean_x: float
    implied_conditional_improvement_bb: float
    complete: bool
    stop_reason: str | None
    elapsed_seconds: float = field(compare=False)


def sample_cell(
    cell: Cell,
    *,
    accepted_target: int,
    lookup: TierProvider,
    max_draws: int | None = None,
    max_seconds: float | None = None,
) -> CellResult:
    if accepted_target <= 0:
        raise ValueError("accepted_target must be positive")
    rng = random.Random(cell.seed)
    started = time.perf_counter()
    accepted = draws = bb_trash = 0
    sum_x = sum_trash_share = 0.0
    stop_reason = None
    while accepted < accepted_target:
        if max_draws is not None and draws >= max_draws:
            stop_reason = "max_draws"
            break
        if max_seconds is not None and time.perf_counter() - started >= max_seconds:
            stop_reason = "max_seconds"
            break
        deal = full_deal(rng, cell.hero_hand)
        draws += 1
        if not earlier_four_fold(deal.earlier_holes, cell.scenario, lookup):
            continue
        accepted += 1
        if lookup.tier(deal.bb_hole) == "Trash":
            share = showdown_share(cell.hero_hand, deal.bb_hole, deal.board)
            bb_trash += 1
            sum_trash_share += share
            sum_x += share
    elapsed = time.perf_counter() - started
    mean_x = sum_x / accepted if accepted else 0.0
    return CellResult(
        candidate_text=cell.candidate_text,
        hero_cards=cell.hero_hand,
        hero_tier=cell.hero_tier,
        scenario=cell.scenario.name,
        prior_fold_condition=cell.scenario.fold_condition(),
        seed=cell.seed,
        accepted_target=accepted_target,
        accepted=accepted,
        candidate_draws=draws,
        acceptance_percent=100 * accepted / draws if draws else 0.0,
        bb_trash_count=bb_trash,
        bb_trash_percent=100 * bb_trash / accepted if accepted else 0.0,
        equity_vs_bb_trash_percent=(
            100 * sum_trash_share / bb_trash if bb_trash else None
        ),
        mean_x=mean_x,
        implied_conditional_improvement_bb=2 * mean_x - 0.5,
        complete=accepted == accepted_target,
        stop_reason=stop_reason,
        elapsed_seconds=elapsed,
    )
