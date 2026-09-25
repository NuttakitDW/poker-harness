"""M5: the Coach (CFR+ / DCFR) and the Auditor (best response, exploitability)."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import auditor, coach, floor, hands, oddsmaker  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

H = hands.index
SHOVE = 1


class AuditorTest(unittest.TestCase):
    def test_best_response_against_shove_everything_call_everything(self):
        spot = Spot((10, 10))
        tree = floor.build(spot)
        sigma = np.zeros((len(tree.nodes), 169, 2))
        sigma[:, :, SHOVE] = 1.0
        report = auditor.audit(tree, sigma)
        # Everyone all in every hand: a coin flip in expectation, so both EVs are 0.
        np.testing.assert_allclose(report.ev, [0, 0], atol=1e-9)
        # SB's best response folds every hand whose shove is worth less than -0.5bb.
        shove = 20 * (hands.M * oddsmaker.two_way()) @ np.ones(169) - 10
        gain = (hands.PRIOR * np.maximum(0, -0.5 - shove)).sum()
        self.assertAlmostEqual(report.gain[0], gain, places=9)


class HeadsUpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = coach.solve(Spot((10, 10)))

    def test_reaches_the_stop_rule(self):
        self.assertLess(self.result.exploitability, 0.01)
        self.assertEqual(self.result.iterations % 50, 0)

    def test_zero_sum(self):
        report = auditor.audit(self.result.tree, self.result.strategy)
        self.assertAlmostEqual(float(report.ev.sum()), 0.0, places=9)

    def test_aces_always_in(self):
        sb, bb = self.result.strategy[0], self.result.strategy[1]
        self.assertAlmostEqual(sb[H("AA"), SHOVE], 1.0, places=3)
        self.assertAlmostEqual(bb[H("AA"), SHOVE], 1.0, places=3)

    def test_display_rounding_keeps_raw_strategy(self):
        grid = self.result.chart(0)
        self.assertEqual(grid.shape, (13, 13))
        raw = self.result.strategy[0][:, SHOVE].reshape(13, 13)
        small = (raw < 0.01) | (raw > 0.99)
        self.assertTrue(np.all((grid[small] == 0) | (grid[small] == 1)))


class MethodsTest(unittest.TestCase):
    def test_every_method_converges_heads_up(self):
        for method in ("cfr", "cfr+", "dcfr"):
            with self.subTest(method=method):
                result = coach.solve(Spot((8, 8)), method=method, target=0.05, max_iters=20000)
                self.assertLess(result.exploitability, 0.05)

    def test_unknown_method_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "method"):
            coach.solve(Spot((8, 8)), method="sgd")


class WarmStartTest(unittest.TestCase):
    def test_warm_start_needs_fewer_iterations(self):
        near = coach.solve(Spot((10, 10)))
        cold = coach.solve(Spot((10.5, 10.5)))
        warm = coach.solve(Spot((10.5, 10.5)), warm=near.strategy)
        self.assertLess(warm.exploitability, 0.01)
        self.assertLessEqual(warm.iterations, cold.iterations)


class ThreeHandedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = coach.solve(Spot((10, 10, 10)), max_iters=10000)

    def test_reaches_the_stop_rule(self):
        self.assertLess(self.result.exploitability, 0.01)

    def test_zero_sum(self):
        report = auditor.audit(self.result.tree, self.result.strategy)
        self.assertAlmostEqual(float(report.ev.sum()), 0.0, places=8)


class AllInByPostingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = coach.solve(Spot((1.5,) * 8, ante=1.0, ante_mode="bb"))

    def test_reaches_the_stop_rule(self):
        self.assertLess(self.result.exploitability, 0.01)

    def test_zero_sum(self):
        report = auditor.audit(self.result.tree, self.result.strategy)
        self.assertAlmostEqual(float(report.ev.sum()), 0.0, places=8)

    def test_everyone_calls_the_forced_big_blind_wider(self):
        self.assertGreater(self.result.range_pct(0), 0.3)


if __name__ == "__main__":
    unittest.main()


class LibraryTest(unittest.TestCase):
    def test_nearest_same_table_size_is_used(self):
        lib = coach.Library()
        self.assertIsNone(lib.nearest(Spot((10, 10))))
        lib.add(coach.solve(Spot((10, 10))))
        lib.add(coach.solve(Spot((5, 5))))
        self.assertEqual(lib.nearest(Spot((9, 9.5))).spot.stacks, (10, 10))
        self.assertIsNone(lib.nearest(Spot((10, 10, 10))))

    def test_a_neighbour_with_a_different_tree_is_not_used(self):
        lib = coach.Library()
        lib.add(coach.solve(Spot((1.5,) * 3, ante=1.0, ante_mode="bb")))  # BB all-in by posting
        self.assertIsNone(lib.nearest(Spot((5.5,) * 3, ante=1.0, ante_mode="bb")))
        again = coach.solve(Spot((5.5,) * 3, ante=1.0, ante_mode="bb"), library=lib)
        self.assertFalse(again.warm)

    def test_solve_with_library_stores_and_warm_starts(self):
        lib = coach.Library()
        coach.solve(Spot((10, 10)), library=lib)
        self.assertEqual(len(lib), 1)
        again = coach.solve(Spot((10.2, 10.2)), library=lib)
        self.assertTrue(again.warm)
        self.assertLess(again.exploitability, 0.01)


class OpponentModelTest(unittest.TestCase):
    def test_heads_up_uses_blockers_multiway_uses_independent_deals(self):
        from pushfold import pricer  # noqa: PLC0415
        np.testing.assert_array_equal(pricer.opponents(2), hands.M)
        np.testing.assert_allclose(pricer.opponents(3), np.tile(hands.PRIOR, (169, 1)))


class FourWayGuardTest(unittest.TestCase):
    def test_pricing_a_four_way_tree_fails_clearly(self):
        from pushfold import pricer  # noqa: PLC0415
        tree = floor.build(Spot((10,) * 4), max_allin=4)
        with self.assertRaisesRegex(ValueError, "3-way"):
            pricer.plan(tree)
