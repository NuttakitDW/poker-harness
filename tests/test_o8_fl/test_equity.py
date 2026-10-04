from __future__ import annotations

import itertools
import unittest

import numpy as np

from o8_fl.cards import card_ids
from o8_fl.equity import exact_river, hand_equity
from o8_fl.evaluator import NO_LOW, omaha_high, omaha_low


def arr(text: str) -> np.ndarray:
    return np.array(card_ids(text), dtype=np.int64)


def brute_river(hole: np.ndarray, board: np.ndarray) -> tuple[float, float]:
    """Exhaustive (high part, low part) of the pot against every opponent hand on a full board."""
    dead = set(hole.tolist()) | set(board.tolist())
    live = [c for c in range(52) if c not in dead]
    my_hi, my_lo = omaha_high(hole, board), omaha_low(hole, board)
    hi = lo = 0.0
    n = 0
    for opp in itertools.combinations(live, 4):
        o = np.array(opp)
        o_hi, o_lo = omaha_high(o, board), omaha_low(o, board)
        h = 1.0 if my_hi > o_hi else 0.5 if my_hi == o_hi else 0.0
        if my_lo == NO_LOW and o_lo == NO_LOW:
            hi += h
        else:
            hi += 0.5 * h
            lo += 0.5 * (1.0 if my_lo < o_lo else 0.5 if my_lo == o_lo else 0.0)
        n += 1
    return hi / n, lo / n


class EquityTest(unittest.TestCase):
    def test_exact_river_matches_brute_force(self) -> None:
        for hole, board in (("As2d3hKs", "4c5d9hJsQd"), ("KsKdQhQc", "Kh7d2c3s8h"), ("8s7d6h5c", "Ah2dJsQsKs")):
            with self.subTest(hole=hole, board=board):
                got = exact_river(arr(hole), arr(board))
                want = brute_river(arr(hole), arr(board))
                self.assertAlmostEqual(got[0], want[0], places=9)
                self.assertAlmostEqual(got[1], want[1], places=9)

    def test_sampled_equity_is_close_to_exact_on_the_river(self) -> None:
        hole, board = arr("As2d3hKs"), arr("4c5d9hJsQd")
        hi, lo, _ = hand_equity(hole, board, 5, 1, 20000, 7)
        exact = exact_river(hole, board)
        self.assertAlmostEqual(hi, exact[0], delta=0.01)
        self.assertAlmostEqual(lo, exact[1], delta=0.01)

    def test_parts_are_bounded_and_high_only_hands_get_no_low(self) -> None:
        hi, lo, sq = hand_equity(arr("KsKhQsQh"), arr("2c3d9h"), 3, 200, 20, 1)
        self.assertEqual(lo, 0.0)
        self.assertTrue(0.0 <= hi <= 1.0)
        self.assertLessEqual(sq, 1.0)
        hi, lo, _ = hand_equity(arr("As2s3hKh"), arr("4c5d9h"), 3, 200, 20, 1)
        self.assertGreater(lo, 0.3)  # nut low made on the flop
        self.assertLessEqual(lo, 0.5)

    def test_preflop_premium_beats_trash(self) -> None:
        good = hand_equity(arr("AsAh2s3h"), np.zeros(5, dtype=np.int64), 0, 3000, 4, 3)
        bad = hand_equity(arr("Ks9h8d2c"), np.zeros(5, dtype=np.int64), 0, 3000, 4, 3)
        self.assertGreater(good[0] + good[1], 0.6)
        self.assertLess(bad[0] + bad[1], 0.5)


if __name__ == "__main__":
    unittest.main()
