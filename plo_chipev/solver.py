"""Seeded external-sampling MCCFR scaffold for preflop PLO4 chip EV."""

from __future__ import annotations

import dataclasses
import math
import random
import time
from typing import Any

import numpy as np

from plo_icm.cards import deal
from plo_icm.game import Action

from .abstraction import hand_observation, information_key_from_observation
from .config import Config
from .game import PreflopState
from .showdown import precompute_ranks, settle_by_ranks


class _BudgetStop(Exception):
    pass


@dataclasses.dataclass
class InfoSet:
    actions: tuple[str, ...]
    regrets: np.ndarray
    strategy_sum: np.ndarray
    visits: int = 0

    @classmethod
    def new(cls, actions: tuple[Action, ...]) -> InfoSet:
        size = len(actions)
        return cls(
            actions=tuple(action.value for action in actions),
            regrets=np.zeros(size, dtype=float),
            strategy_sum=np.zeros(size, dtype=float),
        )

    def current_strategy(self) -> np.ndarray:
        positive = np.maximum(self.regrets, 0.0)
        total = float(positive.sum())
        if total > 0:
            return positive / total
        return np.full(len(positive), 1.0 / len(positive))

    def average_strategy(self) -> np.ndarray:
        total = float(self.strategy_sum.sum())
        if total > 0:
            return self.strategy_sum / total
        # No sampled support means no learned average policy. Uniform is explicit.
        return np.full(len(self.strategy_sum), 1.0 / len(self.strategy_sum))


class Solver:
    """Research approximation for the fixed preflop/check-down game, not ordinary PLO."""

    def __init__(self, config: Config):
        config.validate()
        self.config = config
        self.rng = random.Random(config.seed)
        self.infosets: dict[str, InfoSet] = {}
        self.nodes = 0
        self.completed_iterations = 0
        self.completed_traversals = 0
        self.elapsed_seconds = 0.0
        self.stop_reason = "not_started"
        self._started = 0.0
        self._call_nodes = 0
        self._stop_requested = False
        self._iteration_new_keys: list[str] = []

    def terminal_utilities(self, final: tuple[float, ...]) -> np.ndarray:
        return np.asarray(final, dtype=float) - self.config.stack_bb

    def _terminal(self, state: PreflopState, ranks: tuple[int, ...]) -> np.ndarray:
        base = state.base
        final = settle_by_ranks(
            base.behind,
            base.committed,
            base.folded,
            ranks,
            base.dead_money,
        )
        return self.terminal_utilities(final)

    def _check_budget(self) -> None:
        self.nodes += 1
        self._call_nodes += 1

    def _info(self, key: str, legal: tuple[Action, ...]) -> InfoSet:
        info = self.infosets.get(key)
        if info is None:
            if len(self.infosets) >= self.config.max_infosets:
                raise _BudgetStop
            info = InfoSet.new(legal)
            self.infosets[key] = info
            self._iteration_new_keys.append(key)
        elif info.actions != tuple(action.value for action in legal):
            raise RuntimeError("same information set produced different ordered legal actions")
        return info

    def _sample_index(self, probabilities: np.ndarray) -> int:
        point = self.rng.random()
        cumulative = 0.0
        for index, probability in enumerate(probabilities):
            cumulative += float(probability)
            if point <= cumulative + 1e-15:
                return index
        return len(probabilities) - 1

    def _key(self, state: PreflopState, seat: int, observation: str) -> str:
        return information_key_from_observation(
            state, seat, observation, self.config.hand_abstraction
        )

    def _traverse(
        self,
        state: PreflopState,
        observations: tuple[str, ...],
        ranks: tuple[int, ...],
        target: int,
        deltas: dict[str, np.ndarray],
    ) -> np.ndarray:
        self._check_budget()
        if state.terminal:
            return self._terminal(state, ranks)
        seat = state.actor
        assert seat is not None
        legal = state.legal_actions()
        key = self._key(state, seat, observations[seat])
        info = self._info(key, legal)
        strategy = info.current_strategy().copy()
        if seat != target:
            choice = self._sample_index(strategy)
            return self._traverse(
                state.apply(legal[choice]), observations, ranks, target, deltas
            )
        children = [
            self._traverse(state.apply(action), observations, ranks, target, deltas)
            for action in legal
        ]
        expected: np.ndarray = np.zeros(6, dtype=float)
        for index, child in enumerate(children):
            expected += float(strategy[index]) * child
        regret = np.asarray(
            [child[target] - expected[target] for child in children], dtype=float
        )
        deltas[key] = deltas.get(key, np.zeros(len(legal), dtype=float)) + regret
        return expected

    def _average_pass(
        self,
        state: PreflopState,
        observations: tuple[str, ...],
        own_reach: np.ndarray,
        sampled_reach: float,
        deltas: dict[str, np.ndarray],
    ) -> None:
        self._check_budget()
        if state.terminal:
            return
        seat = state.actor
        assert seat is not None
        legal = state.legal_actions()
        key = self._key(state, seat, observations[seat])
        info = self._info(key, legal)
        strategy = info.current_strategy().copy()
        epsilon = self.config.averaging_epsilon
        sample_policy = (1.0 - epsilon) * strategy + epsilon / len(legal)

        importance_weight = own_reach[seat] / sampled_reach
        contribution = importance_weight * strategy
        deltas[key] = deltas.get(key, np.zeros(len(legal), dtype=float)) + contribution

        choice = self._sample_index(sample_policy)
        next_own_reach = own_reach.copy()
        next_own_reach[seat] *= strategy[choice]
        self._average_pass(
            state.apply(legal[choice]),
            observations,
            next_own_reach,
            sampled_reach * float(sample_policy[choice]),
            deltas,
        )

    def request_stop(self) -> None:
        """Request a stop at the next completed-iteration boundary."""
        self._stop_requested = True

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def _boundary_stop_reason(self, seconds: float | None) -> str | None:
        if self._stop_requested:
            return "signal"
        if self.nodes >= self.config.max_nodes:
            return "max_nodes"
        if len(self.infosets) >= self.config.max_infosets:
            return "max_infosets"
        if seconds is not None and time.perf_counter() - self._started >= seconds:
            return "time_limit_seconds"
        return None

    def train(
        self,
        *,
        additional_iterations: int | None = None,
        seconds: float | None = None,
    ) -> dict[str, Any]:
        iterations = self.config.iterations if additional_iterations is None else additional_iterations
        if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 0:
            raise ValueError("additional_iterations must be a nonnegative integer")
        if seconds is None:
            seconds = self.config.time_limit_seconds
        if seconds is not None and (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds <= 0
        ):
            raise ValueError("seconds must be positive or null")
        self._started = time.perf_counter()
        self._call_nodes = 0
        self._stop_requested = False
        self.stop_reason = "iterations"
        root = PreflopState.new(
            self.config.stack_bb,
            small_blind_bb=self.config.small_blind_bb,
            big_blind_bb=self.config.big_blind_bb,
            max_raises=self.config.max_voluntary_raises,
        )
        for _ in range(iterations):
            reason = self._boundary_stop_reason(seconds)
            if reason is not None:
                self.stop_reason = reason
                break
            rng_before = self.rng.getstate()
            self._iteration_new_keys = []
            try:
                holes, board = deal(self.rng)
                observations = tuple(
                    hand_observation(hole, self.config.hand_abstraction) for hole in holes
                )
                ranks = precompute_ranks(holes, board)
                iteration_regrets: dict[str, np.ndarray] = {}
                iteration_visits: dict[str, int] = {}
                for target in range(6):
                    regret_deltas: dict[str, np.ndarray] = {}
                    self._traverse(root, observations, ranks, target, regret_deltas)
                    for key, delta in regret_deltas.items():
                        iteration_regrets[key] = (
                            iteration_regrets.get(
                                key, np.zeros(len(delta), dtype=float)
                            )
                            + delta
                        )
                        iteration_visits[key] = iteration_visits.get(key, 0) + 1
                average_deltas: dict[str, np.ndarray] = {}
                self._average_pass(root, observations, np.ones(6), 1.0, average_deltas)
            except _BudgetStop:
                for key in self._iteration_new_keys:
                    del self.infosets[key]
                self.rng.setstate(rng_before)
                self.stop_reason = "max_infosets"
                break
            for key, delta in iteration_regrets.items():
                self.infosets[key].regrets += delta
                self.infosets[key].visits += iteration_visits[key]
            for key, delta in average_deltas.items():
                self.infosets[key].strategy_sum += delta
            self.completed_traversals += 6
            self.completed_iterations += 1
            reason = self._boundary_stop_reason(seconds)
            if reason is not None:
                self.stop_reason = reason
                break
        self.elapsed_seconds += time.perf_counter() - self._started
        return self.metadata()

    def metadata(self) -> dict[str, Any]:
        return {
            "algorithm": "external-sampling MCCFR with importance-corrected averaging pass",
            "game": "PLO4 six-max preflop, two pot raises maximum, then check-down",
            "stack_bb": self.config.stack_bb,
            "blinds_bb": [self.config.small_blind_bb, self.config.big_blind_bb],
            "ante_bb": self.config.ante_bb,
            "rake": self.config.rake,
            "format": self.config.format,
            "payouts_or_icm": self.config.payouts_or_icm,
            "utility_units": "bb chip EV (final stack minus starting stack)",
            "hand_abstraction": self.config.hand_abstraction,
            "approximation": True,
            "ordinary_plo_optimum": False,
            "convergence_guarantee": False,
            "iterations_completed": self.completed_iterations,
            "traversals_completed": self.completed_traversals,
            "nodes": self.nodes,
            "infosets": len(self.infosets),
            "stop_reason": self.stop_reason,
            "elapsed_seconds": self.elapsed_seconds,
            "budget_boundary": "completed iterations only",
        }

    def snapshot(self) -> dict[str, Any]:
        """Return deterministic training state for tests and future checkpointing."""
        return {
            "iterations_completed": self.completed_iterations,
            "traversals_completed": self.completed_traversals,
            "nodes": self.nodes,
            "stop_reason": self.stop_reason,
            "elapsed_seconds": self.elapsed_seconds,
            "rng_state": self.rng.getstate(),
            "infosets": {
                key: {
                    "actions": list(info.actions),
                    "regrets": info.regrets.tolist(),
                    "strategy_sum": info.strategy_sum.tolist(),
                    "visits": info.visits,
                }
                for key, info in sorted(self.infosets.items())
            },
        }

    def deterministic_state(self) -> dict[str, Any]:
        """Return checkpoint state excluding wall-clock provenance."""
        state = self.snapshot()
        del state["elapsed_seconds"]
        return state

    def restore_snapshot(self, data: dict[str, Any]) -> None:
        """Restore validated numeric state supplied by the checkpoint module."""
        self.completed_iterations = int(data["iterations_completed"])
        self.completed_traversals = int(data["traversals_completed"])
        self.nodes = int(data["nodes"])
        self.stop_reason = str(data["stop_reason"])
        self.elapsed_seconds = float(data["elapsed_seconds"])
        self.rng.setstate(_nested_tuple(data["rng_state"]))
        restored: dict[str, InfoSet] = {}
        for key, row in data["infosets"].items():
            actions = tuple(row["actions"])
            restored[key] = InfoSet(
                actions=actions,
                regrets=np.asarray(row["regrets"], dtype=float),
                strategy_sum=np.asarray(row["strategy_sum"], dtype=float),
                visits=int(row["visits"]),
            )
        self.infosets = restored


def _nested_tuple(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_nested_tuple(item) for item in value)
    return value
