from __future__ import annotations

import json
import unittest

import numpy as np

from plo_chipev.config import Config
from plo_chipev.solver import InfoSet, Solver
from plo_chipev_fast.hands import HandLookup
from plo_chipev_fast.model import DenseModel, import_legacy_solver
from plo_chipev_fast.tree import PublicTree


class DenseModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = PublicTree.build()
        cls.hands = HandLookup.build()

    def test_legacy_conversion_copies_every_value_and_policy(self) -> None:
        legacy = Solver(Config(iterations=0))
        node = 0
        history = self.tree.histories[node]
        bucket_name = self.hands.bucket_names[17]
        key = json.dumps([0, "features", bucket_name, list(history)], separators=(",", ":"))
        legacy.infosets[key] = InfoSet(
            actions=("fold", "call", "pot"),
            regrets=np.array([-2.0, 4.0, 1.0]),
            strategy_sum=np.array([3.0, 6.0, 1.0]),
            visits=23,
        )
        model = import_legacy_solver(legacy, self.tree, self.hands)
        decision = int(self.tree.decision_index[node])
        np.testing.assert_array_equal(model.regrets[decision, 17], (-2.0, 4.0, 1.0))
        np.testing.assert_array_equal(model.strategy_sum[decision, 17], (3.0, 6.0, 1.0))
        self.assertEqual(model.visits[decision, 17], 23)
        np.testing.assert_allclose(model.average_policy(node, 17), (0.3, 0.6, 0.1))

    def test_import_rejects_unknown_history_action_schema_and_nonfinite_values(self) -> None:
        for key, info, message in (
            (
                json.dumps([0, "features", self.hands.bucket_names[0], ["bad"]]),
                InfoSet(("fold", "call", "pot"), np.zeros(3), np.zeros(3)),
                "public history",
            ),
            (
                json.dumps([0, "features", self.hands.bucket_names[0], []]),
                InfoSet(("call", "fold", "pot"), np.zeros(3), np.zeros(3)),
                "actions",
            ),
            (
                json.dumps([0, "features", self.hands.bucket_names[0], []]),
                InfoSet(("fold", "call", "pot"), np.array([np.nan, 0, 0]), np.zeros(3)),
                "finite",
            ),
        ):
            legacy = Solver(Config(iterations=0))
            legacy.infosets[key] = info
            with self.assertRaisesRegex(ValueError, message):
                import_legacy_solver(legacy, self.tree, self.hands)

    def test_uniform_fallback_is_explicit(self) -> None:
        model = DenseModel.empty(self.tree, self.hands)
        probabilities, fallback, weight = model.policy_for_cards(0, (0, 1, 2, 3))
        np.testing.assert_allclose(probabilities, (1 / 3, 1 / 3, 1 / 3))
        self.assertTrue(fallback)
        self.assertEqual(weight, 0.0)

    def test_legacy_import_rejects_nondefault_averaging_epsilon(self) -> None:
        legacy = Solver(Config(iterations=0, averaging_epsilon=0.2))
        with self.assertRaisesRegex(ValueError, "averaging_epsilon"):
            import_legacy_solver(legacy, self.tree, self.hands)
