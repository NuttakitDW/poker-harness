"""A per-showdown fee charged outside the pot, like GGPoker All-in or Fold."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import auditor, cashier, coach, floor, hands  # noqa: E402
from pushfold.spot import Spot, SpotError  # noqa: E402

SHOVE = 1


class SettleTest(unittest.TestCase):
    def test_every_player_in_the_showdown_pays(self):
        free = cashier.settle(Spot((10, 10, 10, 10)), jammers=(1, 3))
        paid = cashier.settle(Spot((10, 10, 10, 10), fee=0.2), jammers=(1, 3))
        np.testing.assert_allclose(paid.fixed - free.fixed, [0, -0.2, 0, -0.2])
        self.assertEqual(paid.layers, free.layers)  # the pot itself is untouched

    def test_three_way_showdown(self):
        s = cashier.settle(Spot((10, 10, 10, 10), fee=0.2), jammers=(0, 2, 3))
        np.testing.assert_allclose(s.net_for({0: 1, 2: 2, 3: 3}), [19.8, 0, -10.2, -10.2])

    def test_no_fee_without_a_showdown(self):
        spot = Spot((10, 10, 10, 10), fee=0.2)
        np.testing.assert_allclose(cashier.settle(spot, (0,)).net_for({0: 1}), [1.5, 0, -0.5, -1])
        np.testing.assert_allclose(cashier.settle(spot, ()).net_for({3: 1}), [0, 0, -0.5, 0.5])

    def test_fee_leaves_the_table(self):
        spot = Spot((10, 10, 10), fee=0.2)
        for t in floor.build(spot).terminals:
            net = cashier.settle(spot, t.jammers).net_for({s: 1 for s in t.alive})
            charged = 0.2 * len(t.jammers) if len(t.alive) > 1 else 0.0
            self.assertAlmostEqual(float(net.sum()), -charged, places=9)

    def test_negative_fee_is_refused(self):
        with self.assertRaises(SpotError):
            Spot((10, 10), fee=-0.1)


class SolveTest(unittest.TestCase):
    def test_fee_tightens_the_call(self):
        free = coach.solve(Spot((10, 10)))
        paid = coach.solve(Spot((10, 10), fee=0.2))
        call = lambda r: r.range_pct(1, (floor.JAM,))
        self.assertLess(call(paid), call(free))
        self.assertLess(paid.exploitability, 0.01)
        self.assertAlmostEqual(paid.strategy[1][hands.index("AA"), SHOVE], 1.0, places=3)

    def test_expected_fee_is_what_the_table_loses(self):
        result = coach.solve(Spot((10, 10, 10, 10), fee=0.2))
        report = auditor.audit(result.tree, result.strategy)
        self.assertLess(float(report.ev.sum()), 0.0)


if __name__ == "__main__":
    unittest.main()
