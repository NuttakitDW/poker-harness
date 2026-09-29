"""Frozen-policy action values for one unopened PLO tournament hand."""

from __future__ import annotations

import dataclasses
import math
import os
import random
import time
from typing import Iterable

import numpy as np

from .abstraction import AbstractSolver
from .config import Config
from .game import Action, PLOState, settle


@dataclasses.dataclass(frozen=True)
class WeightedValues:
    best: str
    ev: dict[str, float]
    se_vs_best: dict[str, float | None]
    ess: float
    pairwise_se: dict[str, float | None] = dataclasses.field(default_factory=dict)


def weighted_action_values(samples: Iterable[tuple[float, dict[str, float]]]) -> WeightedValues:
    rows = [(float(weight), values) for weight, values in samples if weight > 0]
    total = sum(weight for weight, _ in rows)
    if not rows or total <= 0:
        raise ValueError("unsupported reach: all conditioning weights are zero")
    actions = tuple(rows[0][1])
    ev = {action: sum(weight * values[action] for weight, values in rows) / total for action in actions}
    best = max(actions, key=ev.get)
    sum_w2 = sum(weight * weight for weight, _ in rows)
    ess = total * total / sum_w2
    pairwise = {}
    for action in actions:
        for other in actions:
            deltas = [values[action] - values[other] for _, values in rows]
            mean = sum(weight * delta for (weight, _), delta in zip(rows, deltas)) / total
            variance = sum(weight * weight * (delta - mean) ** 2
                           for (weight, _), delta in zip(rows, deltas)) / (total * total)
            if len(rows) > 1:
                variance *= len(rows) / (len(rows) - 1)
                pairwise[f"{action}|{other}"] = math.sqrt(max(variance, 0))
            else:
                pairwise[f"{action}|{other}"] = None
    se = {}
    for action in actions:
        se[action] = pairwise[f"{action}|{best}"]
    return WeightedValues(best, ev, se, ess, pairwise)


@dataclasses.dataclass(frozen=True)
class HandAdvice:
    action: str
    amount: float
    values: WeightedValues
    samples: int
    untrained_fraction: float
    training: dict
    amounts: dict[str, float] = dataclasses.field(default_factory=dict)
    evaluation_attempts: int = 0
    evaluation_complete: bool = True
    label: str = "one-step action selection with frozen abstract continuation policies; not GTO"


_CACHE: dict[tuple, HandAdvice] = {}


def _policy(solver: AbstractSolver, state: PLOState, holes, board):
    seat = state.actor
    legal = state.legal_actions()
    key = solver._key(state, seat, holes[seat], board)
    info = solver.infosets.get(key)
    if info is None or info.strategy_sum.sum() <= 0:
        return legal, np.full(len(legal), 1 / len(legal)), True
    return legal, info.average(), False


def _rollout(solver: AbstractSolver, state: PLOState, holes, board, deadline: float):
    untrained = decisions = 0
    while not state.terminal:
        if time.perf_counter() >= deadline:
            raise TimeoutError("evaluation budget exhausted")
        legal, policy, missing = _policy(solver, state, holes, board)
        decisions += 1; untrained += int(missing)
        state = state.apply(legal[solver._sample_index(policy)])
    final = settle(state.behind, state.committed, state.folded, holes, board, state.dead_money)
    utility = solver.terminal_utilities(np.array([final]))[0]
    return utility, untrained, decisions


def _fold_to_seat(solver: AbstractSolver, state: PLOState, seat: int, holes, board):
    """Condition on every actual actor before hero folding, including skipped all-ins."""
    reach = 1.0
    missing = decisions = 0
    while not state.terminal and state.actor != seat:
        actor = state.actor
        if actor is None or actor > seat:
            return state, 0.0, missing, decisions
        legal, policy, absent = _policy(solver, state, holes, board)
        decisions += 1; missing += int(absent)
        if Action.FOLD not in legal:
            return state, 0.0, missing, decisions
        index = legal.index(Action.FOLD)
        reach *= float(policy[index])
        state = state.apply(Action.FOLD)
    return state, reach if state.actor == seat else 0.0, missing, decisions


def solve_hand(config: Config, seat: int, hand: tuple[str, ...], *,
               train_seconds: float | None = None, eval_seconds: float | None = None,
               min_samples: int = 32, eval_attempts: int | None = None,
               eval_seed: int | None = None) -> HandAdvice:
    if seat not in range(5):
        raise ValueError("first version supports unopened UTG through SB")
    train_seconds = train_seconds if train_seconds is not None else float(os.getenv("PLO_ADVICE_TRAIN_SECONDS", "15"))
    eval_seconds = eval_seconds if eval_seconds is not None else float(os.getenv("PLO_ADVICE_EVAL_SECONDS", "8"))
    if not math.isfinite(train_seconds) or train_seconds <= 0:
        raise ValueError("train_seconds must be finite and positive")
    if not math.isfinite(eval_seconds) or eval_seconds <= 0:
        raise ValueError("eval_seconds must be finite and positive")
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples <= 0:
        raise ValueError("min_samples must be a positive integer")
    if eval_attempts is not None and (isinstance(eval_attempts, bool)
                                      or not isinstance(eval_attempts, int) or eval_attempts <= 0):
        raise ValueError("eval_attempts must be a positive integer or null")
    if eval_seed is not None and (isinstance(eval_seed, bool) or not isinstance(eval_seed, int)):
        raise ValueError("eval_seed must be an integer or null")
    key = (AbstractSolver.VERSION, config, seat, tuple(sorted(hand)), train_seconds, eval_seconds,
           min_samples, eval_attempts, eval_seed)
    if key in _CACHE:
        return _CACHE[key]
    trained = dataclasses.replace(config, iterations=1_000_000, time_limit=train_seconds,
                                  max_nodes=config.max_nodes, max_infosets=config.max_infosets)
    solver = AbstractSolver(trained, focal_seat=seat, focal_hand=hand)
    solver.train()
    if eval_seed is not None:
        solver.rng = random.Random(eval_seed)
    root = PLOState.new(config.stacks, sb=config.sb, bb=config.bb,
                        ante=config.ante, ante_mode=config.ante_mode,
                        opening_raise_mode=config.opening_raise_mode)
    rows = []
    untrained = decisions = 0
    deadline = time.perf_counter() + eval_seconds
    attempts = 0
    completed_attempts = 0
    while time.perf_counter() < deadline and (eval_attempts is None or attempts < eval_attempts):
        attempts += 1
        holes, board = solver._target_deal()
        state, reach, missing, count = _fold_to_seat(solver, root, seat, holes, board)
        decisions += count; untrained += missing
        if reach <= 0 or state.actor != seat:
            completed_attempts += 1
            continue
        legal = state.legal_actions()
        sample_values = {}
        local_untrained = local_decisions = 0
        common_state = solver.rng.getstate()
        try:
            for action in legal:
                solver.rng.setstate(common_state)
                utility, missing, count = _rollout(solver, state.apply(action), holes, board, deadline)
                sample_values[action.value] = float(utility[seat])
                local_untrained += missing; local_decisions += count
        except TimeoutError:
            break
        rows.append((reach, sample_values))
        completed_attempts += 1
        untrained += local_untrained; decisions += local_decisions
    if not rows:
        raise ValueError(f"evaluation produced no complete paired samples in {attempts} attempts")
    values = weighted_action_values(rows)
    action = Action(values.best)
    replay = root
    while not replay.terminal and replay.actor != seat:
        if Action.FOLD not in replay.legal_actions():
            raise ValueError("hero has no unopened decision after forced posts")
        replay = replay.apply(Action.FOLD)
    legal = replay.legal_actions()
    amounts = {candidate.value: replay.street_put[seat] + replay.action_amount(candidate)
               for candidate in legal}
    amount = amounts[action.value]
    evaluation_complete = eval_attempts is None or completed_attempts == eval_attempts
    result = HandAdvice(values.best, amount, values, len(rows), untrained / max(decisions, 1),
                        solver.metadata(), amounts, completed_attempts, evaluation_complete)
    _CACHE[key] = result
    return result
