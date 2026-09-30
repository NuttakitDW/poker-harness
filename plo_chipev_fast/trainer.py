"""Numba external-sampling MCCFR over the static public tree."""

from __future__ import annotations

import dataclasses
import math
import signal
import time
from typing import Any, Self

import numpy as np
from numba import njit
from phevaluator import _pheval

from .model import DenseModel

MASK64 = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15


class SplitMix64:
    """Small explicit-state PRNG used only for chance deals."""

    def __init__(self, seed: int):
        self.state = int(seed) & MASK64

    def next_u64(self) -> int:
        self.state = (self.state + GOLDEN) & MASK64
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
        return (value ^ (value >> 31)) & MASK64

    def randbelow(self, stop: int) -> int:
        if stop <= 0:
            raise ValueError("stop must be positive")
        # Rejection removes modulo bias while retaining a checkpointable scalar state.
        limit = (1 << 64) - ((1 << 64) % stop)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % stop

    def deal(self) -> tuple[np.ndarray, np.ndarray]:
        deck = list(range(52))
        for index in range(51, 0, -1):
            choice = self.randbelow(index + 1)
            deck[index], deck[choice] = deck[choice], deck[index]
        return (
            np.asarray(deck[:24], dtype=np.int16).reshape(6, 4),
            np.asarray(deck[24:29], dtype=np.int16),
        )


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _random_unit(state: np.ndarray) -> float:
    state[0] = state[0] + np.uint64(GOLDEN)
    value = state[0]
    value = (value ^ (value >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    value = (value ^ (value >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    value = value ^ (value >> np.uint64(31))
    return float(value >> np.uint64(11)) * (1.0 / 9007199254740992.0)


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _probabilities(regrets: np.ndarray, decision: int, bucket: int, count: int) -> tuple[float, float, float]:
    p0 = max(regrets[decision, bucket, 0], 0.0)
    p1 = max(regrets[decision, bucket, 1], 0.0) if count > 1 else 0.0
    p2 = max(regrets[decision, bucket, 2], 0.0) if count > 2 else 0.0
    total = p0 + p1 + p2
    if total <= 0.0:
        uniform = 1.0 / count
        return uniform, uniform if count > 1 else 0.0, uniform if count > 2 else 0.0
    return p0 / total, p1 / total, p2 / total


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _sample(p0: float, p1: float, count: int, rng_state: np.ndarray) -> int:
    point = _random_unit(rng_state)
    if point <= p0 + 1e-15:
        return 0
    if count == 2 or point <= p0 + p1 + 1e-15:
        return 1
    return 2


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _terminal_target_utility(
    node: int,
    target: int,
    behind: np.ndarray,
    sidepot_count: np.ndarray,
    sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray,
    ranks: np.ndarray,
) -> float:
    result = behind[node, target]
    for layer in range(sidepot_count[node]):
        best = 1 << 30
        winners = 0
        target_wins = False
        eligible_mask = sidepot_eligible_mask[node, layer]
        for seat in range(6):
            if eligible_mask & (1 << seat):
                rank = ranks[seat]
                if rank < best:
                    best = rank
                    winners = 1
                    target_wins = seat == target
                elif rank == best:
                    winners += 1
                    if seat == target:
                        target_wins = True
        if target_wins:
            result += sidepot_amount[node, layer] / winners
    return result - 100.0


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _traverse_iterative(
    target: int,
    buckets: np.ndarray,
    ranks: np.ndarray,
    actor: np.ndarray,
    decision_index: np.ndarray,
    children: np.ndarray,
    action_count: np.ndarray,
    behind: np.ndarray,
    sidepot_count: np.ndarray,
    sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray,
    regrets: np.ndarray,
    rng_state: np.ndarray,
    touched_decision: np.ndarray,
    touched_bucket: np.ndarray,
    touched_delta: np.ndarray,
    touched_count: np.ndarray,
    node_counter: np.ndarray,
) -> float:
    """External-sampling DFS using fixed frames instead of native recursion."""
    stack_node = np.empty(32, dtype=np.int32)
    initialized = np.zeros(32, dtype=np.uint8)
    next_action = np.zeros(32, dtype=np.int8)
    counts = np.zeros(32, dtype=np.int8)
    probabilities = np.zeros((32, 3), dtype=np.float64)
    values = np.zeros((32, 3), dtype=np.float64)
    stack_node[0] = 0
    depth = 1
    while depth > 0:
        frame = depth - 1
        node = stack_node[frame]
        seat = actor[node]
        if initialized[frame] == 0:
            node_counter[0] += 1
            initialized[frame] = 1
            next_action[frame] = 0
            if seat < 0:
                returned = _terminal_target_utility(
                    node,
                    target,
                    behind,
                    sidepot_count,
                    sidepot_amount,
                    sidepot_eligible_mask,
                    ranks,
                )
                depth -= 1
                if depth == 0:
                    return returned
                parent = depth - 1
                values[parent, next_action[parent] - 1] = returned
                continue
            decision = decision_index[node]
            bucket = buckets[seat]
            count = action_count[node]
            p0, p1, p2 = _probabilities(regrets, decision, bucket, count)
            probabilities[frame, 0] = p0
            probabilities[frame, 1] = p1
            probabilities[frame, 2] = p2
            counts[frame] = count
            if seat != target:
                choice = _sample(p0, p1, count, rng_state)
                next_action[frame] = choice + 1
                stack_node[depth] = children[node, choice]
                initialized[depth] = 0
                depth += 1
                continue
        if seat != target:
            returned = values[frame, next_action[frame] - 1]
            depth -= 1
            if depth == 0:
                return returned
            parent = depth - 1
            values[parent, next_action[parent] - 1] = returned
            continue
        if next_action[frame] < counts[frame]:
            choice = next_action[frame]
            next_action[frame] += 1
            stack_node[depth] = children[node, choice]
            initialized[depth] = 0
            depth += 1
            continue
        expected = 0.0
        for choice in range(counts[frame]):
            expected += probabilities[frame, choice] * values[frame, choice]
        touched = touched_count[0]
        decision = decision_index[node]
        bucket = buckets[seat]
        touched_decision[touched] = decision
        touched_bucket[touched] = bucket
        for choice in range(counts[frame]):
            touched_delta[touched, choice] = values[frame, choice] - expected
        touched_count[0] += 1
        depth -= 1
        if depth == 0:
            return expected
        parent = depth - 1
        values[parent, next_action[parent] - 1] = expected
    return 0.0


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _average_pass_iterative(
    buckets: np.ndarray,
    actor: np.ndarray,
    decision_index: np.ndarray,
    children: np.ndarray,
    action_count: np.ndarray,
    regrets: np.ndarray,
    rng_state: np.ndarray,
    touched_decision: np.ndarray,
    touched_bucket: np.ndarray,
    touched_delta: np.ndarray,
    touched_count: np.ndarray,
    node_counter: np.ndarray,
) -> None:
    node = 0
    own_reach = np.ones(6, dtype=np.float64)
    sampled_reach = 1.0
    while True:
        node_counter[0] += 1
        seat = actor[node]
        if seat < 0:
            return
        decision = decision_index[node]
        bucket = buckets[seat]
        count = action_count[node]
        p0, p1, p2 = _probabilities(regrets, decision, bucket, count)
        weight = own_reach[seat] / sampled_reach
        touched = touched_count[0]
        touched_decision[touched] = decision
        touched_bucket[touched] = bucket
        touched_delta[touched, 0] = weight * p0
        if count > 1:
            touched_delta[touched, 1] = weight * p1
        if count > 2:
            touched_delta[touched, 2] = weight * p2
        touched_count[0] += 1
        epsilon = 0.05
        q0 = (1.0 - epsilon) * p0 + epsilon / count
        q1 = (1.0 - epsilon) * p1 + epsilon / count
        choice = _sample(q0, q1, count, rng_state)
        probability = p0 if choice == 0 else p1 if choice == 1 else p2
        sample_probability = (
            q0 if choice == 0 else q1 if choice == 1 else (1.0 - q0 - q1)
        )
        own_reach[seat] *= probability
        sampled_reach *= sample_probability
        node = children[node, choice]


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _iteration_kernel(
    buckets: np.ndarray,
    ranks: np.ndarray,
    actor: np.ndarray,
    decision_index: np.ndarray,
    children: np.ndarray,
    action_count: np.ndarray,
    behind: np.ndarray,
    sidepot_count: np.ndarray,
    sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray,
    regrets: np.ndarray,
    strategy_sum: np.ndarray,
    visits: np.ndarray,
    rng_state: np.ndarray,
) -> int:
    capacity = actor.size
    touched_decision = np.empty(capacity, dtype=np.int32)
    touched_bucket = np.empty(capacity, dtype=np.int16)
    touched_delta = np.zeros((capacity, 3), dtype=np.float64)
    touched_count = np.zeros(1, dtype=np.int32)
    node_counter = np.zeros(1, dtype=np.int64)
    for target in range(6):
        _traverse_iterative(
            target, buckets, ranks, actor, decision_index, children,
            action_count, behind, sidepot_count, sidepot_amount,
            sidepot_eligible_mask, regrets,
            rng_state, touched_decision, touched_bucket, touched_delta,
            touched_count, node_counter,
        )
    regret_count = touched_count[0]
    avg_decision = np.empty(32, dtype=np.int32)
    avg_bucket = np.empty(32, dtype=np.int16)
    avg_delta = np.zeros((32, 3), dtype=np.float64)
    avg_count = np.zeros(1, dtype=np.int32)
    _average_pass_iterative(
        buckets, actor, decision_index, children, action_count, regrets,
        rng_state, avg_decision,
        avg_bucket, avg_delta, avg_count, node_counter,
    )
    # Policy remained frozen through all six traversals and the averaging pass.
    for index in range(regret_count):
        decision = touched_decision[index]
        bucket = touched_bucket[index]
        for action in range(3):
            regrets[decision, bucket, action] += touched_delta[index, action]
        visits[decision, bucket] += 1
    for index in range(avg_count[0]):
        decision = avg_decision[index]
        bucket = avg_bucket[index]
        for action in range(3):
            strategy_sum[decision, bucket, action] += avg_delta[index, action]
    return node_counter[0]


def _toy_iteration(
    regrets: np.ndarray,
    strategy_sum: np.ndarray,
    visits: np.ndarray,
    action_utilities: np.ndarray,
) -> None:
    """One frozen-policy full-width update for a one-infoset solvable toy."""
    positive = np.maximum(regrets[0, 0], 0.0)
    strategy = positive / positive.sum() if positive.sum() > 0 else np.full(3, 1 / 3)
    expected = float(strategy @ action_utilities)
    delta = action_utilities - expected
    average_delta = strategy.copy()
    regrets[0, 0] += delta
    strategy_sum[0, 0] += average_delta
    visits[0, 0] += 1


@dataclasses.dataclass
class FastTrainer:
    model: DenseModel
    chance_rng: SplitMix64
    sampling_state: np.ndarray
    completed_iterations: int = 0
    completed_traversals: int = 0
    nodes: int = 0
    imported_iterations: int = 0
    imported_traversals: int = 0
    imported_nodes: int = 0
    active_training_seconds: float = 0.0
    wall_seconds: float = 0.0
    stop_reason: str = "not_started"
    _stop_requested: bool = False

    def __init__(self, model: DenseModel, *, chance_seed: int, sampling_seed: int):
        self.model = model
        self.chance_rng = SplitMix64(chance_seed)
        seed = sampling_seed & MASK64
        self.sampling_state = np.asarray([seed if seed else GOLDEN], dtype=np.uint64)
        self.completed_iterations = 0
        self.completed_traversals = 0
        self.nodes = 0
        self.imported_iterations = 0
        self.imported_traversals = 0
        self.imported_nodes = 0
        self.active_training_seconds = 0.0
        self.wall_seconds = 0.0
        self.stop_reason = "not_started"
        self._stop_requested = False

    @classmethod
    def from_state(cls, model: DenseModel, state: dict[str, Any]) -> FastTrainer:
        cls.validate_state(state)
        trainer = cls(
            model,
            chance_seed=state["chance_state"],
            sampling_seed=state["sampling_state"],
        )
        trainer.chance_rng.state = state["chance_state"]
        trainer.sampling_state[0] = np.uint64(state["sampling_state"])
        trainer.completed_iterations = state["iterations_completed"]
        trainer.completed_traversals = state["traversals_completed"]
        trainer.nodes = state["nodes"]
        trainer.imported_iterations = state["imported_iterations"]
        trainer.imported_traversals = state["imported_traversals"]
        trainer.imported_nodes = state["imported_nodes"]
        trainer.active_training_seconds = float(state["active_training_seconds"])
        trainer.wall_seconds = float(state["wall_seconds"])
        trainer.stop_reason = state["stop_reason"]
        return trainer

    @staticmethod
    def validate_state(state: Any) -> None:
        required = {
            "chance_state",
            "sampling_state",
            "iterations_completed",
            "traversals_completed",
            "nodes",
            "imported_iterations",
            "imported_traversals",
            "imported_nodes",
            "new_backend_iterations",
            "active_training_seconds",
            "wall_seconds",
            "stop_reason",
        }
        if not isinstance(state, dict) or set(state) != required:
            raise ValueError("trainer state schema is incompatible")
        counters = (
            "iterations_completed",
            "traversals_completed",
            "nodes",
            "imported_iterations",
            "imported_traversals",
            "imported_nodes",
            "new_backend_iterations",
        )
        if any(
            isinstance(state[name], bool)
            or not isinstance(state[name], int)
            or state[name] < 0
            for name in counters
        ):
            raise ValueError("trainer counters must be nonnegative integers")
        for name in ("chance_state", "sampling_state"):
            if (
                isinstance(state[name], bool)
                or not isinstance(state[name], int)
                or not 0 <= state[name] < 1 << 64
            ):
                raise ValueError("trainer RNG state is invalid")
        for name in ("active_training_seconds", "wall_seconds"):
            value = state[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("trainer timing provenance is invalid")
        if state["active_training_seconds"] > state["wall_seconds"] + 1e-9:
            raise ValueError("trainer timing provenance is inconsistent")
        if state["iterations_completed"] < state["imported_iterations"]:
            raise ValueError("trainer iteration provenance is inconsistent")
        if state["traversals_completed"] < state["imported_traversals"]:
            raise ValueError("trainer traversal provenance is inconsistent")
        if state["nodes"] < state["imported_nodes"]:
            raise ValueError("trainer node provenance is inconsistent")
        if state["new_backend_iterations"] != (
            state["iterations_completed"] - state["imported_iterations"]
        ):
            raise ValueError("trainer iteration provenance is inconsistent")
        if state["traversals_completed"] != state["iterations_completed"] * 6:
            raise ValueError("trainer traversal count is inconsistent")
        if state["imported_traversals"] != state["imported_iterations"] * 6:
            raise ValueError("trainer imported traversal count is inconsistent")
        if state["stop_reason"] not in {
            "not_started",
            "iterations",
            "signal",
            "time_limit_seconds",
        }:
            raise ValueError("trainer stop reason is invalid")

    def state_dict(self) -> dict[str, Any]:
        return {
            "chance_state": self.chance_rng.state,
            "sampling_state": int(self.sampling_state[0]),
            "iterations_completed": self.completed_iterations,
            "traversals_completed": self.completed_traversals,
            "nodes": self.nodes,
            "imported_iterations": self.imported_iterations,
            "imported_traversals": self.imported_traversals,
            "imported_nodes": self.imported_nodes,
            "new_backend_iterations": self.completed_iterations - self.imported_iterations,
            "active_training_seconds": self.active_training_seconds,
            "wall_seconds": self.wall_seconds,
            "stop_reason": self.stop_reason,
        }

    def deterministic_state(self) -> dict[str, Any]:
        state = self.state_dict()
        del state["active_training_seconds"]
        del state["wall_seconds"]
        return state

    def request_stop(self) -> None:
        self._stop_requested = True

    def _prepare_chance(self) -> tuple[np.ndarray, np.ndarray, float]:
        started = time.perf_counter()
        holes, board = self.chance_rng.deal()
        buckets = np.asarray(
            [self.model.hands.bucket_for_cards(tuple(sorted(map(int, hand)))) for hand in holes],
            dtype=np.int16,
        )
        board_tuple = tuple(int(value) for value in board)
        ranks = np.asarray(
            [
                int(_pheval.evaluate_plo4_cards(*(board_tuple + tuple(int(value) for value in hand))))
                for hand in holes
            ],
            dtype=np.int32,
        )
        return buckets, ranks, time.perf_counter() - started

    def train(self, *, iterations: int, seconds: float | None = None) -> dict[str, Any]:
        if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 0:
            raise ValueError("iterations must be a nonnegative integer")
        if seconds is not None and (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds <= 0
        ):
            raise ValueError("seconds must be finite and positive")
        wall_started = time.perf_counter()
        starting_iterations = self.completed_iterations
        active = 0.0
        chance_seconds = 0.0
        self._stop_requested = False
        self.stop_reason = "iterations"
        for _ in range(iterations):
            if self._stop_requested:
                self.stop_reason = "signal"
                break
            if seconds is not None and time.perf_counter() - wall_started >= seconds:
                self.stop_reason = "time_limit_seconds"
                break
            buckets, ranks, chance_time = self._prepare_chance()
            chance_seconds += chance_time
            kernel_started = time.perf_counter()
            self.nodes += int(
                _iteration_kernel(
                    buckets,
                    ranks,
                    self.model.tree.actor,
                    self.model.tree.decision_index,
                    self.model.tree.children,
                    self.model.tree.action_count,
                    self.model.tree.behind,
                    self.model.tree.sidepot_count,
                    self.model.tree.sidepot_amount,
                    self.model.tree.sidepot_eligible_mask,
                    self.model.regrets,
                    self.model.strategy_sum,
                    self.model.visits,
                    self.sampling_state,
                )
            )
            active += time.perf_counter() - kernel_started
            self.completed_iterations += 1
            self.completed_traversals += 6
            if seconds is not None and time.perf_counter() - wall_started >= seconds:
                self.stop_reason = "time_limit_seconds"
                break
        wall = time.perf_counter() - wall_started
        self.active_training_seconds += active
        self.wall_seconds += wall
        return {
            **self.state_dict(),
            "iterations_this_call": self.completed_iterations - starting_iterations,
            "wall_seconds_this_call": wall,
            "kernel_seconds_this_call": active,
            "chance_rank_seconds_this_call": chance_seconds,
            "iterations_per_wall_second": (
                (self.completed_iterations - self.imported_iterations) / self.wall_seconds
                if self.wall_seconds
                else 0.0
            ),
            "iterations_per_kernel_second": (
                (self.completed_iterations - self.imported_iterations)
                / self.active_training_seconds
                if self.active_training_seconds
                else 0.0
            ),
            "iterations_per_wall_second_this_call": (
                (self.completed_iterations - starting_iterations) / wall if wall else 0.0
            ),
            "approximation": True,
            "ordinary_plo_optimum": False,
        }


class SignalStop:
    """Install reversible SIGINT/SIGTERM handlers that request a boundary stop."""

    def __init__(self, trainer: FastTrainer):
        self.trainer = trainer
        self.previous: dict[int, Any] = {}

    def __enter__(self) -> Self:
        def handler(_signum: int, _frame: Any) -> None:
            self.trainer.request_stop()

        for signum in (signal.SIGINT, signal.SIGTERM):
            self.previous[signum] = signal.getsignal(signum)
            signal.signal(signum, handler)
        return self

    def __exit__(self, *_args: object) -> None:
        for signum, previous in self.previous.items():
            signal.signal(signum, previous)
