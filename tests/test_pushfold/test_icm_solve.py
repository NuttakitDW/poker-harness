"""The Coach solving for ICM instead of chips."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import auditor, coach, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

BUBBLE = icm.Payouts((50, 30, 20))


class HeadsUpTest(unittest.TestCase):
    def test_two_left_plays_exactly_like_chip_ev(self):
        # With two players left ICM is a straight line in chips, and regret matching does not
        # care about scale: the same iterations give the same strategy.
        fixed = dict(target=0.0, max_iters=300, check_every=300)
        chip = coach.solve(Spot((10, 10)), **fixed)
        prize = coach.solve(Spot((10, 10)), payouts=icm.Payouts((65, 35)), **fixed)
        np.testing.assert_allclose(prize.strategy, chip.strategy, atol=1e-9)


class BubbleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spot = Spot((10, 10, 10, 10))
        cls.chip = coach.solve(spot)
        cls.prize = coach.solve(spot, payouts=BUBBLE)

    def test_reaches_the_stop_rule(self):
        self.assertLess(self.prize.exploitability, 0.01)
        self.assertEqual(self.prize.payouts, BUBBLE)

    def test_evs_add_up_to_zero(self):
        report = auditor.audit(self.prize.tree, self.prize.strategy, payouts=BUBBLE)
        self.assertAlmostEqual(float(report.ev.sum()), 0.0, places=4)

    def test_every_call_is_tighter_on_the_bubble(self):
        # Busting before the money costs far more than doubling up wins.
        for node in self.prize.tree.nodes:
            if node.facing:
                with self.subTest(seat=node.seat, history=node.history):
                    self.assertLess(self.prize.range_pct(node.seat, node.history),
                                    self.chip.range_pct(node.seat, node.history) / 2)

    def test_first_in_shoves_get_wider_because_callers_tighten(self):
        for node in self.prize.tree.nodes:
            if not node.facing:
                with self.subTest(seat=node.seat):
                    self.assertGreater(self.prize.range_pct(node.seat, node.history),
                                       self.chip.range_pct(node.seat, node.history))


class LibraryTest(unittest.TestCase):
    def test_chip_ev_and_icm_solves_are_not_neighbours(self):
        lib = coach.Library()
        coach.solve(Spot((10, 10, 10)), library=lib)
        again = coach.solve(Spot((10, 10, 10.5)), payouts=icm.Payouts((70, 30)), library=lib)
        self.assertFalse(again.warm)
        third = coach.solve(Spot((10, 10, 11)), payouts=icm.Payouts((70, 30)), library=lib)
        self.assertTrue(third.warm)


if __name__ == "__main__":
    unittest.main()
