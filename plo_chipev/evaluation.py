"""Frozen-average-policy holdout evaluation and behavioral reporting."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from plo_icm.cards import deal
from plo_icm.game import Action

from .abstraction import hand_observation, information_key_from_observation
from .game import PreflopState
from .showdown import precompute_ranks, settle_by_ranks
from .solver import Solver

POSITION_NAMES = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
TIERS = ("Premium", "Speculative", "Marginal", "Trash")


class EvaluationDeadlineExceeded(RuntimeError):
    """Raised when a bounded solve cannot start or continue another complete hand."""


def _canonical_json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _profile_snapshot(solver: Solver) -> dict[str, tuple[tuple[str, ...], tuple[float, ...], float]]:
    return {
        key: (
            info.actions,
            tuple(float(value) for value in info.average_strategy()),
            float(info.strategy_sum.sum()),
        )
        for key, info in solver.infosets.items()
    }


def _snapshot_hash(
    profile: dict[str, tuple[tuple[str, ...], tuple[float, ...], float]],
) -> str:
    serialized = {
        key: {"actions": row[0], "average": row[1], "weight": row[2]}
        for key, row in sorted(profile.items())
    }
    return hashlib.sha256(_canonical_json(serialized)).hexdigest()


def frozen_profile_hash(solver: Solver) -> str:
    profile = _profile_snapshot(solver)
    return _snapshot_hash(profile)


class FrozenAveragePolicy:
    """A total policy: unsupported or zero-weight states are explicitly uniform."""

    def __init__(self, solver: Solver):
        snapshot = _profile_snapshot(solver)
        self._profile = MappingProxyType(snapshot)
        self.hand_abstraction = solver.config.hand_abstraction
        self.profile_hash = _snapshot_hash(snapshot)

    def distribution(
        self,
        state: PreflopState,
        seat: int,
        observation: str,
        legal: tuple[Action, ...],
    ) -> tuple[np.ndarray, bool, float]:
        key = information_key_from_observation(
            state, seat, observation, self.hand_abstraction
        )
        row = self._profile.get(key)
        expected = tuple(action.value for action in legal)
        if row is None or row[2] <= 0:
            return np.full(len(legal), 1.0 / len(legal)), True, 0.0
        actions, probabilities, weight = row
        if actions != expected:
            raise RuntimeError("frozen policy legal-action schema mismatch")
        return np.asarray(probabilities, dtype=float), False, weight


def domain_seed(domain: str, user_seed: int, *parts: object) -> int:
    """Derive a reproducible RNG stream that cannot alias the training stream."""
    material = json.dumps(
        ["plo-chipev-rng-v2", domain, user_seed, *parts],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _sample_index(rng: random.Random, probabilities: np.ndarray) -> int:
    point = rng.random()
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += float(probability)
        if point <= cumulative + 1e-15:
            return index
    return len(probabilities) - 1


def opportunity(state: PreflopState) -> str:
    if state.raises == 2:
        return "facing_3bet"
    if state.raises == 1:
        return "facing_open"
    saw_limp = any(":call:" in event for event in state.history)
    return "unraised_after_limps" if saw_limp else "first_in"


def action_label(state: PreflopState, action: Action) -> str:
    stage = opportunity(state)
    if action == Action.FOLD:
        return "fold"
    if action == Action.CHECK:
        return "freecheck"
    if action == Action.CALL:
        actor = state.actor
        assert actor is not None
        prior_actions = [
            event.split(":")[2]
            for event in state.history
            if int(event.split(":")[1]) == actor
        ]
        if stage == "facing_open" and "call" in prior_actions:
            return "limp_call"
        return {
            "first_in": "limp",
            "unraised_after_limps": "limp",
            "facing_open": "coldcall",
            "facing_3bet": "call_3bet",
        }[stage]
    if state.raises == 0:
        return "iso" if stage == "unraised_after_limps" else "pot_open"
    return "pot_3bet"


_PLO_TYPE: Any | None = None


def _plo_type() -> Any:
    global _PLO_TYPE
    if _PLO_TYPE is not None:
        return _PLO_TYPE
    root = Path(__file__).resolve().parents[1]
    voice = root / "scripts" / "voice"
    spec = importlib.util.spec_from_file_location("plo_chipev_hwang", voice / "plo_type.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load existing Hwang-inspired classifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(voice))
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    finally:
        sys.path.remove(str(voice))
    _PLO_TYPE = module
    return module


def hwang_tier(hole: tuple[str, ...]) -> str:
    classifier = _plo_type()
    hand = classifier.read(" ".join(hole))
    if hand is None:
        raise RuntimeError(f"classifier rejected physical PLO hand: {hole}")
    tier = classifier.classify(hand).tier
    if tier not in TIERS:
        raise RuntimeError(f"classifier returned unknown tier: {tier}")
    return tier


def _clustered_ci(samples: list[float]) -> dict[str, float | int]:
    count = len(samples)
    mean = sum(samples) / count if count else 0.0
    if count < 2:
        lower = 0.0
        upper = 1.0
    else:
        variance = sum((value - mean) ** 2 for value in samples) / (count - 1)
        radius = 1.96 * math.sqrt(variance / count)
        lower = max(0.0, mean - radius)
        upper = min(1.0, mean + radius)
    return {
        "clusters": count,
        "mean": mean,
        "lower_95": lower,
        "upper_95": upper,
        "interval_available": count >= 2,
    }


def evaluate_profile(
    solver: Solver,
    *,
    hands: int,
    seed: int,
    deadline: float | None = None,
    honor_stop_request: bool = False,
) -> dict[str, Any]:
    if isinstance(hands, bool) or not isinstance(hands, int) or hands <= 0:
        raise ValueError("hands must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    policy = FrozenAveragePolicy(solver)
    derived_seed = domain_seed("behavior-evaluation", seed, policy.profile_hash)
    rng = random.Random(derived_seed)
    vpip = [0] * 6
    net = [0.0] * 6
    table_vpip: list[float] = []
    tier_population: Counter[str] = Counter()
    tier_vpip: Counter[str] = Counter()
    tier_actions: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    tier_opportunities: dict[str, Counter[str]] = defaultdict(Counter)
    support: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    support_weight: dict[tuple[str, str], float] = defaultdict(float)
    maximum_table_zero_sum_error = 0.0

    for _ in range(hands):
        if honor_stop_request and solver.stop_requested:
            raise EvaluationDeadlineExceeded("behavior evaluation stop requested")
        if deadline is not None and time.perf_counter() >= deadline:
            raise EvaluationDeadlineExceeded(
                "behavior evaluation deadline exhausted before a complete hand"
            )
        holes, board = deal(rng)
        if len({card for hole in holes for card in hole} | set(board)) != 29:
            raise RuntimeError("deal did not contain 29 distinct physical cards")
        ranks = precompute_ranks(holes, board)
        observations = tuple(
            hand_observation(hole, solver.config.hand_abstraction) for hole in holes
        )
        tiers = tuple(hwang_tier(hole) for hole in holes)
        tier_population.update(tiers)
        voluntary = [False] * 6
        state = PreflopState.new(
            solver.config.stack_bb,
            small_blind_bb=solver.config.small_blind_bb,
            big_blind_bb=solver.config.big_blind_bb,
            max_raises=solver.config.max_voluntary_raises,
        )
        while not state.terminal:
            if honor_stop_request and solver.stop_requested:
                raise EvaluationDeadlineExceeded("behavior evaluation stop requested")
            if deadline is not None and time.perf_counter() >= deadline:
                raise EvaluationDeadlineExceeded(
                    "behavior evaluation deadline exhausted during a partial hand"
                )
            seat = state.actor
            assert seat is not None
            legal = state.legal_actions()
            stage = opportunity(state)
            tier_opportunities[tiers[seat]][stage] += 1
            probabilities, fallback, weight = policy.distribution(
                state, seat, observations[seat], legal
            )
            position = POSITION_NAMES[seat]
            support[position][stage]["decisions"] += 1
            support[position][stage]["fallback"] += int(fallback)
            support_weight[(position, stage)] += weight
            action = legal[_sample_index(rng, probabilities)]
            label = action_label(state, action)
            tier_actions[tiers[seat]][stage][label] += 1
            if action in (Action.CALL, Action.POT):
                voluntary[seat] = True
            state = state.apply(action)
        final = settle_by_ranks(
            state.base.behind,
            state.base.committed,
            state.base.folded,
            ranks,
            state.base.dead_money,
        )
        gains = [stack - solver.config.stack_bb for stack in final]
        maximum_table_zero_sum_error = max(
            maximum_table_zero_sum_error, abs(sum(gains))
        )
        for seat in range(6):
            vpip[seat] += int(voluntary[seat])
            tier_vpip[tiers[seat]] += int(voluntary[seat])
            net[seat] += gains[seat]
        table_vpip.append(sum(voluntary) / 6)

    support_report: dict[str, dict[str, Any]] = {}
    for position, stages in support.items():
        support_report[position] = {}
        for stage, counts in stages.items():
            decisions = counts["decisions"]
            support_report[position][stage] = {
                "decisions": decisions,
                "fallback_decisions": counts["fallback"],
                "fallback_rate": counts["fallback"] / decisions,
                "mean_average_weight": support_weight[(position, stage)] / decisions,
            }
    tiers_report = {}
    for tier in TIERS:
        population = tier_population[tier]
        tiers_report[tier] = {
            "population": population,
            "vpip_count": tier_vpip[tier],
            "vpip": tier_vpip[tier] / population if population else None,
            "actions_by_opportunity": {
                stage: {
                    "opportunities": tier_opportunities[tier][stage],
                    "counts": dict(sorted(tier_actions[tier][stage].items())),
                    "rates": {
                        action: count / tier_opportunities[tier][stage]
                        for action, count in sorted(tier_actions[tier][stage].items())
                    },
                }
                for stage in sorted(tier_opportunities[tier])
            },
        }
    return {
        "schema_version": 1,
        "evaluation": "independent holdout simulation of frozen average strategy",
        "profile_hash": policy.profile_hash,
        "seed": seed,
        "rng_domain": "behavior-evaluation",
        "derived_seed": derived_seed,
        "table_hands": hands,
        "assumptions": {
            "variant": "PLO4 high",
            "format": "six-max tournament chip EV",
            "stack_bb": solver.config.stack_bb,
            "blinds_bb": [
                solver.config.small_blind_bb,
                solver.config.big_blind_bb,
            ],
            "ante_bb": solver.config.ante_bb,
            "rake": solver.config.rake,
            "payouts_or_icm": solver.config.payouts_or_icm,
            "postflop": "forced check-down",
            "ordinary_plo_optimum": False,
        },
        "overall_vpip": _clustered_ci(table_vpip),
        "vpip_ci_method": "normal 95% CI over table-hand clusters (six seats kept dependent)",
        "by_position": {
            POSITION_NAMES[seat]: {
                "vpip_count": vpip[seat],
                "vpip": vpip[seat] / hands,
                "net_bb_per_100": 100 * net[seat] / hands,
            }
            for seat in range(6)
        },
        "table_net_bb_per_100": 100 * sum(net) / hands,
        "maximum_table_zero_sum_error_bb": maximum_table_zero_sum_error,
        "hwang_inspired_reporting_only": tiers_report,
        "average_policy_support": support_report,
        "fallback_policy": "uniform over ordered legal actions",
        "descriptive_30_percent_vpip": {
            "hypothesis": 0.30,
            "observed": sum(vpip) / (6 * hands),
            "difference": sum(vpip) / (6 * hands) - 0.30,
            "optimality_claim": False,
        },
    }
