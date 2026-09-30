"""Dense feature-bucket model and strict legacy conversion."""

from __future__ import annotations

import dataclasses
import json

import numpy as np

from plo_chipev.solver import Solver

from .hands import HandLookup
from .tree import ACTION_NAMES, PublicTree


@dataclasses.dataclass
class DenseModel:
    tree: PublicTree
    hands: HandLookup
    regrets: np.ndarray
    strategy_sum: np.ndarray
    visits: np.ndarray
    source_checkpoint_hash: str | None = None

    @classmethod
    def empty(cls, tree: PublicTree, hands: HandLookup) -> DenseModel:
        shape = (tree.decision_count, hands.bucket_count, 3)
        return cls(
            tree=tree,
            hands=hands,
            regrets=np.zeros(shape, dtype=np.float64),
            strategy_sum=np.zeros(shape, dtype=np.float64),
            visits=np.zeros(shape[:2], dtype=np.int64),
        )

    def _row(self, node: int, bucket: int, source: np.ndarray) -> np.ndarray:
        if not 0 <= node < self.tree.node_count or self.tree.actor[node] < 0:
            raise ValueError("node must be a public decision node")
        if not 0 <= bucket < self.hands.bucket_count:
            raise ValueError("unknown bucket")
        count = int(self.tree.action_count[node])
        return source[int(self.tree.decision_index[node]), bucket, :count]

    def current_policy(self, node: int, bucket: int) -> np.ndarray:
        regrets = self._row(node, bucket, self.regrets)
        positive = np.maximum(regrets, 0.0)
        total = float(positive.sum())
        return positive / total if total > 0 else np.full(len(regrets), 1.0 / len(regrets))

    def average_policy(self, node: int, bucket: int) -> np.ndarray:
        weights = self._row(node, bucket, self.strategy_sum)
        total = float(weights.sum())
        return weights / total if total > 0 else np.full(len(weights), 1.0 / len(weights))

    def policy_for_cards(
        self, node: int, cards: tuple[int, int, int, int]
    ) -> tuple[np.ndarray, bool, float]:
        bucket = self.hands.bucket_for_cards(cards)
        row = self._row(node, bucket, self.strategy_sum)
        weight = float(row.sum())
        return self.average_policy(node, bucket), weight <= 0.0, weight

    def validate(self) -> None:
        expected = (self.tree.decision_count, self.hands.bucket_count, 3)
        if self.regrets.shape != expected or self.strategy_sum.shape != expected:
            raise ValueError("dense model shape is incompatible")
        if self.visits.shape != expected[:2]:
            raise ValueError("visit shape is incompatible")
        if self.regrets.dtype != np.float64 or self.strategy_sum.dtype != np.float64:
            raise ValueError("dense floating arrays must be float64")
        if self.visits.dtype != np.int64:
            raise ValueError("visits must be int64")
        if not np.isfinite(self.regrets).all() or not np.isfinite(self.strategy_sum).all():
            raise ValueError("model values must be finite")
        if np.any(self.strategy_sum < 0) or np.any(self.visits < 0):
            raise ValueError("strategy weights and visits must be nonnegative")


def import_legacy_solver(
    solver: Solver,
    tree: PublicTree,
    hands: HandLookup,
    *,
    source_checkpoint_hash: str | None = None,
) -> DenseModel:
    """Strictly copy every legacy infoset into its dense node/bucket/action row."""
    if solver.config.hand_abstraction != "features":
        raise ValueError("only feature-abstraction checkpoints can be imported")
    if solver.config.averaging_epsilon != 0.05:
        raise ValueError("legacy averaging_epsilon must be exactly 0.05")
    model = DenseModel.empty(tree, hands)
    bucket_ids = {name: index for index, name in enumerate(hands.bucket_names)}
    seen: set[tuple[int, int]] = set()
    for key, info in solver.infosets.items():
        try:
            payload = json.loads(key)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("malformed legacy information key") from exc
        if not isinstance(payload, list) or len(payload) != 4:
            raise ValueError("malformed legacy information key")
        seat, abstraction, bucket_name, raw_history = payload
        if abstraction != "features" or not isinstance(raw_history, list):
            raise ValueError("incompatible legacy abstraction or public history")
        history = tuple(raw_history)
        node = tree.history_to_node.get(history)
        if node is None:
            raise ValueError("legacy key contains an unknown public history")
        if tree.actor[node] != seat:
            raise ValueError("legacy key actor does not match public history")
        bucket = bucket_ids.get(bucket_name)
        if bucket is None:
            raise ValueError("legacy key contains an unknown feature bucket")
        count = int(tree.action_count[node])
        expected_actions = tuple(
            ACTION_NAMES[int(value)] for value in tree.action_ids[node, :count]
        )
        if info.actions != expected_actions:
            raise ValueError("legacy actions are incompatible with public tree")
        regrets = np.asarray(info.regrets, dtype=np.float64)
        strategy_sum = np.asarray(info.strategy_sum, dtype=np.float64)
        if regrets.shape != (count,) or strategy_sum.shape != (count,):
            raise ValueError("legacy value shape is incompatible")
        if not np.isfinite(regrets).all() or not np.isfinite(strategy_sum).all():
            raise ValueError("legacy values must be finite")
        if np.any(strategy_sum < 0) or info.visits < 0:
            raise ValueError("legacy strategy weights and visits must be nonnegative")
        decision = int(tree.decision_index[node])
        address = (decision, bucket)
        if address in seen:
            raise ValueError("multiple legacy keys map to one dense row")
        seen.add(address)
        model.regrets[decision, bucket, :count] = regrets
        model.strategy_sum[decision, bucket, :count] = strategy_sum
        model.visits[decision, bucket] = info.visits
    model.source_checkpoint_hash = source_checkpoint_hash
    model.validate()
    return model
