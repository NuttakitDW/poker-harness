"""Preregistered candidates, authored marginal scenarios, and separated RNG streams."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .tiers import CandidateTier, classify_candidates

CANDIDATE_TEXTS = (
    "QsJs7c6c",
    "KsQs4c2c",
    "AsKs3c2c",
    "As9s3d2c",
    "Ks9s6d6c",
    "4s4h3d3c",
    "9s7s5d3c",
    "Js9s7d6c",
    "QsJs7d6c",
    "AsAhAc5d",
    "Ks8s4d2c",
    "Js8s7d6c",
)
EARLIER_POSITIONS = ("UTG", "HJ", "CO", "BTN")


@dataclass(frozen=True)
class Scenario:
    name: str
    marginal_enters: frozenset[str]

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


SCENARIOS = (
    Scenario("marginal_enters_btn_only", frozenset({"BTN"})),
    Scenario("marginal_enters_co_btn", frozenset({"CO", "BTN"})),
    Scenario("marginal_enters_hj_co_btn", frozenset({"HJ", "CO", "BTN"})),
)


def domain_seed(user_seed: int, phase: str, candidate: str, scenario: str) -> int:
    material = json.dumps(
        ["plo-thesis-audit-v1", user_seed, phase, candidate, scenario],
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


@dataclass(frozen=True)
class Cell:
    candidate_text: str
    hero_hand: tuple[int, int, int, int]
    hero_tier: str
    scenario: Scenario
    seed: int


@dataclass(frozen=True)
class SamplePlan:
    phase: str
    user_seed: int
    accepted_per_cell: int
    valid_candidates: tuple[CandidateTier, ...]
    discarded_candidates: tuple[CandidateTier, ...]
    cells: tuple[Cell, ...]
    simultaneous_cells: int
    status: str = "planned"


def freeze_plan(*, seed: int, phase: str) -> SamplePlan:
    if phase not in {"pilot", "main"}:
        raise ValueError("phase must be pilot or main")
    accepted = 2_000 if phase == "pilot" else 50_000
    validation = classify_candidates(CANDIDATE_TEXTS)
    cells = tuple(
        Cell(
            candidate.text,
            candidate.hand,
            candidate.tier,
            scenario,
            domain_seed(seed, phase, candidate.text, scenario.name),
        )
        for candidate in validation.valid
        for scenario in SCENARIOS
    )
    return SamplePlan(
        phase=phase,
        user_seed=seed,
        accepted_per_cell=accepted,
        valid_candidates=validation.valid,
        discarded_candidates=validation.discarded,
        cells=cells,
        simultaneous_cells=len(cells),
    )
