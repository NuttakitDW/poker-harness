"""M2: the Oddsmaker's equity tables."""

import random
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import equity_eval  # noqa: E402
from pushfold import hands, oddsmaker  # noqa: E402

H = hands.index


class EvaluatorTest(unittest.TestCase):
    def test_vectorised_strength_matches_the_voice_evaluator(self):
        rng = random.Random(11)
        deals = np.array([rng.sample(range(52), 7) for _ in range(2000)], dtype=np.int16)
        ours = oddsmaker.strength(deals[:, :2], deals[:, 2:])
        for row, deal in enumerate(deals):
            board = equity_eval.boards_of(deal[None, 2:].astype(np.int8))
            want = int(equity_eval.strength((int(deal[0]), int(deal[1])), board)[0])
            self.assertEqual(int(ours[row]), want)


class TwoWayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e2 = oddsmaker.load().e2

    def test_shape_and_zero_sum(self):
        self.assertEqual(self.e2.shape, (169, 169))
        np.testing.assert_allclose(self.e2 + self.e2.T, 1.0, atol=1e-9)

    def test_aces_vs_kings(self):
        self.assertAlmostEqual(self.e2[H("AA"), H("KK")], 0.82, delta=0.006)

    def test_ducks_are_a_slight_favourite_over_ako(self):
        self.assertTrue(0.5 < self.e2[H("22"), H("AKo")] < 0.54)

    def test_a_class_pair_equals_the_combo_weighted_exact_average(self):
        # AKs vs QQ: every compatible combo pair averaged, straight from pokerkit-exact equity.
        import equity  # noqa: PLC0415
        result = equity.calculate(["AKs", "QQ"])
        self.assertTrue(result.exact)
        self.assertAlmostEqual(self.e2[H("AKs"), H("QQ")], result.players[0].equity, places=9)


class ThreeWayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = oddsmaker.load()

    def test_three_way_equities_sum_to_one(self):
        eq3 = self.t.eq3
        rng = np.random.default_rng(3)
        for a, b, c in rng.integers(0, 169, size=(300, 3)):
            total = eq3[a, b, c] + eq3[b, a, c] + eq3[c, a, b]
            self.assertAlmostEqual(float(total), 1.0, places=5)

    def test_symmetric_in_the_two_opponents(self):
        np.testing.assert_allclose(self.t.eq3, self.t.eq3.transpose(0, 2, 1), atol=1e-6)

    def test_side_pot_pair_is_zero_sum(self):
        np.testing.assert_allclose(self.t.pw + self.t.pw.transpose(1, 0, 2), 1.0, atol=1e-6)

    def test_side_pot_pair_is_close_to_plain_heads_up(self):
        # A dead third hand moves heads-up equity a little, never a lot.
        a, b, c = H("AKo"), H("QQ"), H("JTs")
        self.assertAlmostEqual(float(self.t.pw[a, b, c]), float(self.t.e2[a, b]), delta=0.03)

    def test_aces_kings_queens(self):
        aa, kk, qq = H("AA"), H("KK"), H("QQ")
        self.assertAlmostEqual(float(self.t.eq3[aa, kk, qq]), 0.66, delta=0.03)
        self.assertGreater(self.t.eq3[kk, aa, qq], self.t.eq3[qq, aa, kk])

    def test_impossible_triples_are_flagged(self):
        aa = H("AA")
        self.assertFalse(self.t.possible[aa, aa, H("AKo")])
        self.assertTrue(self.t.possible[aa, aa, H("KK")])


if __name__ == "__main__":
    unittest.main()
