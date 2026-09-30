"""Information-constrained sampled-batch best-response upper bound."""

from __future__ import annotations

import dataclasses
import math
import random
import secrets
import time
from collections import defaultdict
from collections.abc import Callable, Hashable
from typing import Any

from plo_icm.cards import deal

from .abstraction import hand_observation
from .evaluation import FrozenAveragePolicy, domain_seed
from .game import PreflopState
from .showdown import precompute_ranks, settle_by_ranks
from .solver import Solver

RANGE_BB = 600.0
TARGET_BB = 0.015
BOUND_SOURCE = "Maurer and Pontil (2009), Theorem 4: https://arxiv.org/pdf/0907.3740"


def _index_from_point(point: float, probabilities: Any) -> int:
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += float(probability)
        if point <= cumulative + 1e-15:
            return index
    return len(probabilities) - 1


@dataclasses.dataclass
class SampleNode:
    """One node in a sampled opponent/chance tree used by both policy values."""

    kind: str
    payoff: float | None = None
    child: SampleNode | None = None
    children: tuple[SampleNode, ...] = ()
    info_key: Hashable | None = None
    probabilities: tuple[float, ...] = ()
    depth: int = 0
    choice: int | None = None

    @classmethod
    def leaf(cls, payoff: float) -> SampleNode:
        return cls(kind="leaf", payoff=float(payoff))

    @classmethod
    def opponent(cls, child: SampleNode) -> SampleNode:
        return cls(kind="opponent", child=child)

    @classmethod
    def target(
        cls,
        key: Hashable,
        children: tuple[SampleNode, ...],
        probabilities: tuple[float, ...],
        depth: int,
    ) -> SampleNode:
        if len(children) != len(probabilities) or not children:
            raise ValueError("target node children and probabilities must align")
        return cls(
            kind="target",
            children=children,
            info_key=key,
            probabilities=probabilities,
            depth=depth,
        )


class EvaluationBudgetExceeded(RuntimeError):
    """Raised before expanding another node when a certificate guard is exhausted."""


@dataclasses.dataclass
class ExpansionBudget:
    max_nodes: int | None = None
    deadline: float | None = None
    stop_requested: Callable[[], bool] | None = None
    nodes: int = 0

    def consume(self) -> None:
        if self.stop_requested is not None and self.stop_requested():
            raise EvaluationBudgetExceeded("certificate stop requested")
        if self.max_nodes is not None and self.nodes >= self.max_nodes:
            raise EvaluationBudgetExceeded("certificate max_nodes exhausted")
        if self.deadline is not None and time.perf_counter() >= self.deadline:
            raise EvaluationBudgetExceeded("certificate deadline exhausted")
        self.nodes += 1

def baseline_value(node: SampleNode) -> float:
    if node.kind == "leaf":
        assert node.payoff is not None
        return node.payoff
    if node.kind == "opponent":
        assert node.child is not None
        return baseline_value(node.child)
    if node.kind != "target":
        raise ValueError(f"unknown sample node kind: {node.kind}")
    return sum(
        probability * baseline_value(child)
        for probability, child in zip(node.probabilities, node.children)
    )


def optimized_value(node: SampleNode) -> float:
    if node.kind == "leaf":
        assert node.payoff is not None
        return node.payoff
    if node.kind == "opponent":
        assert node.child is not None
        return optimized_value(node.child)
    if node.kind != "target" or node.choice is None:
        raise ValueError("target group has not been optimized bottom-up")
    return optimized_value(node.children[node.choice])


def grouped_best_response(roots: list[SampleNode]) -> tuple[float, dict[Hashable, int]]:
    """Optimize one deterministic action per identical own-information group."""
    groups: dict[Hashable, list[SampleNode]] = defaultdict(list)

    def collect(node: SampleNode) -> None:
        if node.kind == "opponent":
            assert node.child is not None
            collect(node.child)
        elif node.kind == "target":
            assert node.info_key is not None
            groups[node.info_key].append(node)
            for child in node.children:
                collect(child)

    for root in roots:
        collect(root)
    choices: dict[Hashable, int] = {}
    ordered = sorted(groups.items(), key=lambda item: item[1][0].depth, reverse=True)
    for key, occurrences in ordered:
        action_count = len(occurrences[0].children)
        if any(len(node.children) != action_count for node in occurrences):
            raise RuntimeError("identical information group has different legal actions")
        totals = [
            sum(optimized_value(node.children[action]) for node in occurrences)
            for action in range(action_count)
        ]
        choice = max(range(action_count), key=totals.__getitem__)
        choices[key] = choice
        for node in occurrences:
            node.choice = choice
    return sum(optimized_value(root) for root in roots) / len(roots), choices


def target_information_key(
    hole: tuple[str, ...], history: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Use physical own cards and public history; never canonicalize or add hidden state."""
    return tuple(sorted(hole)), history


class _BatchBuilder:
    def __init__(
        self,
        solver: Solver,
        target: int,
        rng: random.Random,
        policy: FrozenAveragePolicy,
        budget: ExpansionBudget,
    ):
        self.solver = solver
        self.target = target
        self.rng = rng
        self.policy = policy
        self.budget = budget
        self.tape: dict[tuple[int, int, tuple[str, ...]], float] = {}
        self.nodes = 0
        self.fallback_decisions = 0
        self.decisions = 0

    def build(
        self,
        state: PreflopState,
        holes: tuple[tuple[str, ...], ...],
        observations: tuple[str, ...],
        ranks: tuple[int, ...],
        deal_index: int,
    ) -> SampleNode:
        self.budget.consume()
        self.nodes += 1
        if state.terminal:
            final = settle_by_ranks(
                state.base.behind,
                state.base.committed,
                state.base.folded,
                ranks,
                state.base.dead_money,
            )
            return SampleNode.leaf(final[self.target] - self.solver.config.stack_bb)
        actor = state.actor
        assert actor is not None
        legal = state.legal_actions()
        probabilities, fallback, _ = self.policy.distribution(
            state, actor, observations[actor], legal
        )
        self.decisions += 1
        self.fallback_decisions += int(fallback)
        if actor == self.target:
            own_key = target_information_key(holes[actor], state.history)
            children = tuple(
                self.build(state.apply(action), holes, observations, ranks, deal_index)
                for action in legal
            )
            return SampleNode.target(
                own_key,
                children,
                tuple(float(value) for value in probabilities),
                len(state.history),
            )
        tape_key = (deal_index, actor, state.history)
        point = self.tape.get(tape_key)
        if point is None:
            point = self.rng.random()
            self.tape[tape_key] = point
        choice = _index_from_point(point, probabilities)
        return SampleNode.opponent(
            self.build(
                state.apply(legal[choice]), holes, observations, ranks, deal_index
            )
        )


def _seed(
    base: int,
    target: int,
    batch: int,
    *,
    round_index: int = 1,
    nonce: str = "legacy",
    profile_hash: str = "",
) -> int:
    return domain_seed(
        "certificate", base, round_index, nonce, profile_hash, target, batch
    )


def sampled_batch_gap(
    solver: Solver,
    *,
    target: int,
    hands: int,
    seed: int,
    policy: FrozenAveragePolicy | None = None,
    budget: ExpansionBudget | None = None,
) -> tuple[float, dict[str, int]]:
    if isinstance(target, bool) or not isinstance(target, int) or target not in range(6):
        raise ValueError("target must be a seat and hands must be positive")
    if isinstance(hands, bool) or not isinstance(hands, int) or hands <= 0:
        raise ValueError("target must be a seat and hands must be positive")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    rng = random.Random(seed)
    frozen = policy if policy is not None else FrozenAveragePolicy(solver)
    expansion_budget = budget if budget is not None else ExpansionBudget()
    builder = _BatchBuilder(solver, target, rng, frozen, expansion_budget)
    roots = []
    root = PreflopState.new(
        solver.config.stack_bb,
        small_blind_bb=solver.config.small_blind_bb,
        big_blind_bb=solver.config.big_blind_bb,
        max_raises=solver.config.max_voluntary_raises,
    )
    for deal_index in range(hands):
        holes, board = deal(rng)
        observations = tuple(
            hand_observation(hole, solver.config.hand_abstraction) for hole in holes
        )
        ranks = precompute_ranks(holes, board)
        roots.append(builder.build(root, holes, observations, ranks, deal_index))
    baseline = sum(baseline_value(node) for node in roots) / hands
    optimized, _ = grouped_best_response(roots)
    raw_gap = optimized - baseline
    if raw_gap < -1e-9:
        raise RuntimeError("optimized batch value is structurally below baseline")
    gap = max(0.0, raw_gap)
    range_bb = solver.config.players * solver.config.stack_bb
    if gap > range_bb + 1e-9:
        raise RuntimeError("batch gap exceeded the configured total-stack range")
    return gap, {
        "nodes": builder.nodes,
        "decisions": builder.decisions,
        "fallback_decisions": builder.fallback_decisions,
    }


def empirical_bernstein_upper(
    samples: list[float],
    *,
    alpha: float,
    round_index: int,
    range_bb: float = RANGE_BB,
) -> float:
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not math.isfinite(alpha)
        or not 0 < alpha < 1
        or isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or round_index < 1
        or isinstance(range_bb, bool)
        or not isinstance(range_bb, (int, float))
        or not math.isfinite(range_bb)
        or range_bb <= 0
    ):
        raise ValueError("alpha must be in (0,1) and round_index must be positive")
    count = len(samples)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= range_bb
        for value in samples
    ):
        raise ValueError("batch gaps must be finite and inside the configured range")
    if count < 2:
        return range_bb
    mean = sum(samples) / count
    variance = sum((value - mean) ** 2 for value in samples) / (count - 1)
    delta = alpha / (6 * round_index * (round_index + 1))
    logarithm = math.log(2 / delta)
    radius = math.sqrt(2 * variance * logarithm / count)
    radius += 7 * range_bb * logarithm / (3 * (count - 1))
    return min(range_bb, mean + radius)


def statistical_floor(
    *,
    batches: int,
    alpha: float,
    round_index: int,
    range_bb: float = RANGE_BB,
) -> float:
    """Best possible bound for the plan: zero observed mean and zero variance."""
    if isinstance(batches, bool) or not isinstance(batches, int) or batches < 2:
        raise ValueError("batches must be an integer of at least two")
    # Reuse the public bound's strict validation of alpha, round and range.
    empirical_bernstein_upper(
        [0.0, 0.0], alpha=alpha, round_index=round_index, range_bb=range_bb
    )
    delta = alpha / (6 * round_index * (round_index + 1))
    floor = 7 * range_bb * math.log(2 / delta) / (3 * (batches - 1))
    return min(range_bb, floor)


def certify_profile(
    solver: Solver,
    *,
    batches: int,
    batch_hands: int,
    seed: int,
    alpha: float,
    round_index: int,
    max_nodes: int | None = None,
    max_seconds: float | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    if (
        isinstance(batches, bool)
        or not isinstance(batches, int)
        or batches < 2
        or isinstance(batch_hands, bool)
        or not isinstance(batch_hands, int)
        or batch_hands <= 0
    ):
        raise ValueError("certification requires at least two positive complete batches")
    if max_nodes is not None and (
        isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes <= 0
    ):
        raise ValueError("max_nodes must be positive or null")
    if max_seconds is not None and (
        isinstance(max_seconds, bool)
        or not isinstance(max_seconds, (int, float))
        or not math.isfinite(max_seconds)
        or max_seconds <= 0
    ):
        raise ValueError("max_seconds must be positive or null")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not math.isfinite(alpha)
        or not 0 < alpha < 1
    ):
        raise ValueError("alpha must be finite and in (0,1)")
    if (
        isinstance(round_index, bool)
        or not isinstance(round_index, int)
        or round_index < 1
    ):
        raise ValueError("round_index must be a positive integer")
    certificate_nonce = nonce if nonce is not None else secrets.token_hex(16)
    if not certificate_nonce:
        raise ValueError("certificate nonce must not be empty")
    policy = FrozenAveragePolicy(solver)
    range_bb = solver.config.players * solver.config.stack_bb
    target_bb = 0.01 * (
        solver.config.small_blind_bb + solver.config.big_blind_bb
    )
    best_case_floor = statistical_floor(
        batches=batches,
        alpha=alpha,
        round_index=round_index,
        range_bb=range_bb,
    )
    started = time.perf_counter()
    budget = ExpansionBudget(
        max_nodes=max_nodes,
        deadline=None if max_seconds is None else started + max_seconds,
        stop_requested=lambda: solver.stop_requested,
    )
    results: dict[str, Any] = {}
    complete = True
    for target in range(6):
        gaps: list[float] = []
        fallback = decisions = 0
        for batch in range(batches):
            try:
                gap, counters = sampled_batch_gap(
                    solver,
                    target=target,
                    hands=batch_hands,
                    seed=_seed(
                        seed,
                        target,
                        batch,
                        round_index=round_index,
                        nonce=certificate_nonce,
                        profile_hash=policy.profile_hash,
                    ),
                    policy=policy,
                    budget=budget,
                )
            except EvaluationBudgetExceeded:
                complete = False
                break
            gaps.append(gap)
            fallback += counters["fallback_decisions"]
            decisions += counters["decisions"]
        upper = empirical_bernstein_upper(
            gaps if len(gaps) == batches else [],
            alpha=alpha,
            round_index=round_index,
            range_bb=range_bb,
        )
        results[str(target)] = {
            "completed_batches": len(gaps),
            "planned_batches": batches,
            "batch_hands": batch_hands,
            "empirical_optimized_batch_gaps_bb": gaps,
            "mean_empirical_optimized_batch_gap_bb": sum(gaps) / len(gaps) if gaps else None,
            "confidence_upper_bound_bb": upper,
            "fallback_decisions": fallback,
            "decisions": decisions,
        }
        if not complete:
            break
    all_seats_complete = complete and len(results) == 6 and all(
        row["completed_batches"] == batches for row in results.values()
    )
    target_met = all_seats_complete and all(
        row["confidence_upper_bound_bb"] < target_bb for row in results.values()
    )
    return {
        "schema_version": 1,
        "name": "high-confidence upper bound on maximum unilateral improvement in forced-checkdown game",
        "profile_hash": policy.profile_hash,
        "seed": seed,
        "rng_domain": "certificate",
        "rng_nonce": certificate_nonce,
        "raw_estimate_label": "EMPIRICAL OPTIMIZED BATCH GAP",
        "bound": "one-sided empirical Bernstein with six-seat union bound and sequential alpha spending",
        "bound_source": BOUND_SOURCE,
        "alpha": alpha,
        "evaluation_round": round_index,
        "range_bb": [0.0, range_bb],
        "target_bb_per_hand": target_bb,
        "target_definition": "1% of the configured initial blind pot",
        "best_case_statistical_floor_bb": best_case_floor,
        "planned_budget_can_reach_target": best_case_floor < target_bb,
        "complete": all_seats_complete,
        "certified": target_met,
        "ordinary_plo_claim": False,
        "forced_checkdown_game_only": True,
        "nodes": budget.nodes,
        "elapsed_seconds": time.perf_counter() - started,
        "incomplete_reason": None if all_seats_complete else "resource guard or partial evaluation",
        "by_target_seat": results,
        "proof_note": (
            "Each fixed legal deviation has an unbiased value under iid chance deals and "
            "sampled opponent tapes. Maximizing the batch value over information-consistent "
            "policies before expectation is upper-biased (E max >= max E)."
        ),
    }
