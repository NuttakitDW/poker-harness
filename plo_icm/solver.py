"""Seeded external-sampling MCCFR for the reduced-action PLO game.

This is a research approximation: exact card/showdown and betting rules, but a deliberately
small fold/check/call/raise-to-2bb/pot action abstraction. Sparse exact-card support is reported rather
than extrapolated into an invented chart.
"""

from __future__ import annotations

import dataclasses
import json
import math
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from pushfold.icm import Payouts, value

from .cards import canonical_cards, deal, parse_cards
from .config import Config
from .game import Action, PLOState, settle


class UnseenInformationSet(LookupError):
    pass


class _BudgetStop(Exception):
    pass


@dataclasses.dataclass
class InfoSet:
    actions: tuple[str, ...]
    regrets: np.ndarray
    strategy_sum: np.ndarray
    visits: int = 0

    @classmethod
    def new(cls, actions: tuple[Action, ...]) -> "InfoSet":
        n = len(actions)
        return cls(tuple(a.value for a in actions), np.zeros(n), np.zeros(n))

    def strategy(self) -> np.ndarray:
        positive = np.maximum(self.regrets, 0)
        total = positive.sum()
        return positive / total if total > 0 else np.full(len(positive), 1 / len(positive))

    def average(self) -> np.ndarray:
        total = self.strategy_sum.sum()
        return self.strategy_sum / total if total > 0 else self.strategy()


class Solver:
    def __init__(self, config: Config):
        config.validate()
        self.config = config
        self.rng = random.Random(config.seed)
        self.infosets: dict[str, InfoSet] = {}
        self.nodes = 0
        self.completed_iterations = 0
        self.completed_traversals = 0
        self.stop_reason = "not_started"
        self.elapsed = 0.0
        self._began = 0.0
        self._icm_cache: dict[tuple[float, ...], np.ndarray] = {}

    def terminal_utilities(self, final: np.ndarray) -> np.ndarray:
        cfg = self.config
        payouts = Payouts(cfg.payouts, crowd=cfg.outside_count, crowd_stack=cfg.outside_stack)
        chip_units = value(final, cfg.stacks, payouts)
        total_chips = sum(cfg.stacks) + cfg.outside_count * cfg.outside_stack
        return chip_units * (sum(cfg.payouts) / total_chips)

    def _terminal(self, state: PLOState, holes: tuple[tuple[str, ...], ...],
                  board: tuple[str, ...]) -> np.ndarray:
        final = settle(state.behind, state.committed, state.folded, holes, board, state.dead_money)
        key = tuple(round(x, 9) for x in final)
        if key not in self._icm_cache:
            self._icm_cache[key] = self.terminal_utilities(np.array([key]))[0]
        return self._icm_cache[key]

    @staticmethod
    def _shown_board(street: int, board: tuple[str, ...]) -> tuple[str, ...]:
        return board[:(0, 3, 4, 5)[street]]

    def _key(self, state: PLOState, seat: int, hole: tuple[str, ...], board: tuple[str, ...]) -> str:
        shown = self._shown_board(state.street, board)
        hand, public = canonical_cards(hole, shown)
        payload = [seat, state.street, hand, public, list(state.history),
                   [round(x, 9) for x in state.behind], [round(x, 9) for x in state.street_put],
                   sorted(state.folded)]
        return json.dumps(payload, separators=(",", ":"))

    def _check_budget(self) -> None:
        self.nodes += 1
        if self.nodes > self.config.max_nodes:
            self.stop_reason = "max_nodes"
            raise _BudgetStop
        if self.config.time_limit is not None and time.perf_counter() - self._began >= self.config.time_limit:
            self.stop_reason = "time_limit"
            raise _BudgetStop

    def _info(self, key: str, legal: tuple[Action, ...]) -> InfoSet:
        info = self.infosets.get(key)
        if info is None:
            if len(self.infosets) >= self.config.max_infosets:
                self.stop_reason = "max_infosets"
                raise _BudgetStop
            info = self.infosets[key] = InfoSet.new(legal)
        elif info.actions != tuple(a.value for a in legal):
            raise RuntimeError("same information set produced different legal actions")
        return info

    def _sample_index(self, probabilities: np.ndarray) -> int:
        point, total = self.rng.random(), 0.0
        for i, probability in enumerate(probabilities):
            total += float(probability)
            if point <= total + 1e-15:
                return i
        return len(probabilities) - 1

    def _traverse(self, state: PLOState, holes: tuple[tuple[str, ...], ...], board: tuple[str, ...],
                  target: int, deltas: dict[str, np.ndarray]) -> np.ndarray:
        self._check_budget()
        if state.terminal:
            return self._terminal(state, holes, board)
        seat = state.actor
        assert seat is not None
        legal = state.legal_actions()
        key = self._key(state, seat, holes[seat], board)
        info = self._info(key, legal)
        sigma = info.strategy().copy()  # frozen for this traversal; updates are committed afterward
        if seat != target:
            action = legal[self._sample_index(sigma)]
            return self._traverse(state.apply(action), holes, board, target, deltas)
        children = [self._traverse(state.apply(action), holes, board, target, deltas) for action in legal]
        expected = sum(float(sigma[i]) * child for i, child in enumerate(children))
        regret = np.array([child[target] - expected[target] for child in children])
        deltas[key] = deltas.get(key, np.zeros(len(legal))) + regret
        return expected

    def _average_pass(self, state: PLOState, holes: tuple[tuple[str, ...], ...], board: tuple[str, ...],
                      own_reach: np.ndarray, sampled_reach: float,
                      deltas: dict[str, np.ndarray]) -> None:
        self._check_budget()
        if state.terminal:
            return
        seat = state.actor
        assert seat is not None
        legal = state.legal_actions()
        key = self._key(state, seat, holes[seat], board)
        info = self._info(key, legal)
        sigma = info.strategy().copy()
        epsilon = self.config.averaging_epsilon
        q = (1 - epsilon) * sigma + epsilon / len(legal)
        weight = own_reach[seat] / sampled_reach
        deltas[key] = deltas.get(key, np.zeros(len(legal))) + weight * sigma
        choice = self._sample_index(q)
        next_own = own_reach.copy()
        next_own[seat] *= sigma[choice]
        self._average_pass(state.apply(legal[choice]), holes, board, next_own,
                           sampled_reach * q[choice], deltas)

    def train(self) -> dict[str, Any]:
        self._began = time.perf_counter()
        self.stop_reason = "iterations"
        root = PLOState.new(self.config.stacks, sb=self.config.sb, bb=self.config.bb,
                            ante=self.config.ante, ante_mode=self.config.ante_mode,
                            opening_raise_mode=self.config.opening_raise_mode)
        try:
            for _ in range(self.config.iterations):
                holes, board = deal(self.rng)
                for target in range(6):
                    regret_delta: dict[str, np.ndarray] = {}
                    self._traverse(root, holes, board, target, regret_delta)
                    for key, delta in regret_delta.items():
                        self.infosets[key].regrets += delta
                        self.infosets[key].visits += 1
                    self.completed_traversals += 1
                average_delta: dict[str, np.ndarray] = {}
                self._average_pass(root, holes, board, np.ones(6), 1.0, average_delta)
                for key, delta in average_delta.items():
                    self.infosets[key].strategy_sum += delta
                self.completed_iterations += 1
        except _BudgetStop:
            pass
        self.elapsed += time.perf_counter() - self._began
        return self.metadata()

    def metadata(self) -> dict[str, Any]:
        return {"algorithm": "external-sampling MCCFR with full-support averaging pass",
                "game": "PLO4 high, six-max, fold/check/call/raise-to-2bb/pot abstraction",
                "opening_raise_mode": self.config.opening_raise_mode,
                "approximation": True, "convergence_guarantee": False,
                "coverage": "only visited exact-card information sets",
                "iterations_completed": self.completed_iterations,
                "traversals_completed": self.completed_traversals, "nodes": self.nodes,
                "infosets": len(self.infosets), "stop_reason": self.stop_reason,
                "elapsed_seconds": self.elapsed, "utility_units": "payout currency"}

    def query(self, seat: int, hand: str, board: str | tuple[str, ...] = ()) -> list[dict[str, Any]]:
        hole = parse_cards(hand, 4)
        public_cards = parse_cards(board)
        if len(public_cards) not in (0, 3, 4, 5):
            raise ValueError("board must have 0, 3, 4, or 5 public cards")
        if len(set(hole + public_cards)) != len(hole) + len(public_cards):
            raise ValueError("duplicate card across hand and board")
        canonical_hand, canonical_board = canonical_cards(hole, public_cards)
        found = []
        for key, info in self.infosets.items():
            payload = json.loads(key)
            if (payload[0] == seat and payload[2] == canonical_hand and payload[3] == canonical_board
                    and info.visits > 0 and info.strategy_sum.sum() > 0):
                found.append({"history": payload[4], "actions": list(info.actions),
                              "strategy": info.average().tolist(), "support": info.visits,
                              "average_weight": float(info.strategy_sum.sum())})
        if not found:
            raise UnseenInformationSet("strategy unavailable: this exact hand/public state was not visited")
        return found

    def to_dict(self) -> dict[str, Any]:
        return {"format": "plo-icm-mccfr-v2", "config": self.config.to_dict(), "metadata": self.metadata(),
                "training": {"completed_iterations": self.completed_iterations, "nodes": self.nodes},
                "infosets": {key: {"actions": list(info.actions), "regrets": info.regrets.tolist(),
                                    "strategy_sum": info.strategy_sum.tolist(), "visits": info.visits}
                             for key, info in sorted(self.infosets.items())}}

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Solver":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("config"), dict) or not isinstance(data.get("infosets"), dict):
            raise ValueError("malformed model: expected config and infosets objects")
        if not isinstance(data.get("metadata", {}), dict):
            raise ValueError("malformed model metadata")
        if data.get("format") != "plo-icm-mccfr-v2":
            raise ValueError("unsupported model format or incompatible action schema; retrain with v2")
        solver = cls(Config.from_dict(data["config"]))
        for key, row in data["infosets"].items():
            try:
                payload = json.loads(key)
                actions = tuple(row["actions"])
                regrets = np.array(row["regrets"], dtype=float)
                strategy_sum = np.array(row["strategy_sum"], dtype=float)
                visits = row["visits"]
            except (TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("malformed infoset row") from exc
            valid_key = (isinstance(payload, list) and len(payload) == 8
                         and isinstance(payload[0], int) and 0 <= payload[0] < 6
                         and isinstance(payload[1], int) and 0 <= payload[1] <= 3
                         and isinstance(payload[2], str) and isinstance(payload[3], str)
                         and isinstance(payload[4], list) and isinstance(payload[5], list)
                         and len(payload[5]) == 6 and isinstance(payload[6], list)
                         and len(payload[6]) == 6 and isinstance(payload[7], list))
            if (not valid_key or not actions or any(a not in {x.value for x in Action} for a in actions)
                    or regrets.shape != (len(actions),) or strategy_sum.shape != regrets.shape
                    or not np.isfinite(regrets).all() or not np.isfinite(strategy_sum).all()
                    or (strategy_sum < 0).any() or isinstance(visits, bool)
                    or not isinstance(visits, int) or visits < 0):
                raise ValueError("malformed infoset values")
            solver.infosets[key] = InfoSet(actions, regrets, strategy_sum, visits)
        meta = data.get("metadata", {})
        integers = (meta.get("iterations_completed", 0), meta.get("traversals_completed", 0),
                    meta.get("nodes", 0))
        elapsed = meta.get("elapsed_seconds", 0)
        if (any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in integers)
                or isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
                or not math.isfinite(elapsed) or elapsed < 0):
            raise ValueError("malformed model training counters")
        solver.completed_iterations = int(meta.get("iterations_completed", 0))
        solver.completed_traversals = int(meta.get("traversals_completed", 0))
        solver.nodes = int(meta.get("nodes", 0))
        solver.stop_reason = str(meta.get("stop_reason", "loaded"))
        solver.elapsed = float(meta.get("elapsed_seconds", 0))
        return solver
