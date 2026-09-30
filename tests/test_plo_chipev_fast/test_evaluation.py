from __future__ import annotations

import unittest

from plo_chipev_fast.evaluation import evaluate_profile
from plo_chipev_fast.hands import HandLookup
from plo_chipev_fast.model import DenseModel
from plo_chipev_fast.trainer import FastTrainer
from plo_chipev_fast.tree import PublicTree


class EvaluationTest(unittest.TestCase):
    def test_fresh_seeded_holdout_reports_support_vpip_and_zero_sum(self) -> None:
        tree = PublicTree.build()
        hands = HandLookup.build()
        trainer = FastTrainer(DenseModel.empty(tree, hands), chance_seed=3, sampling_seed=4)
        report = evaluate_profile(trainer, hands=8, seed=8001)
        self.assertEqual(report["table_hands"], 8)
        self.assertEqual(report["model_identity"]["iterations_completed"], 0)
        self.assertEqual(report["assumptions"]["postflop"], "forced check-down")
        self.assertFalse(report["claims"]["ordinary_plo_optimum"])
        self.assertLess(report["maximum_table_zero_sum_error_bb"], 1e-8)
        self.assertEqual(set(report["by_seat"]), {"UTG", "HJ", "CO", "BTN", "SB", "BB"})
        self.assertIn("Premium", report["by_tier"])
        self.assertGreater(report["support"]["decisions"], 0)
        self.assertEqual(report["support"]["fallback_fraction"], 1.0)
        self.assertNotEqual(report["rng"]["derived_seed"], seed_to_avoid := 8001)
        self.assertEqual(seed_to_avoid, 8001)

