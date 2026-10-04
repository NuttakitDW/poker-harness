from __future__ import annotations

import random
import unittest

import numpy as np

from o8_fl.cards import card_ids
from o8_fl.evaluator import omaha_high
from o8_fl.features import (EARLY_KEYS, RIVER_KEYS, early_key, flush_draw, high_class, low_draw,
                            made_low_rank, protected, river_key, straight_draw)


def arr(text: str) -> np.ndarray:
    return np.array(card_ids(text), dtype=np.int64)


class HighClassTest(unittest.TestCase):
    def cls(self, hole: str, board: str) -> int:
        b = arr(board)
        return high_class(arr(hole), b, len(b))

    def test_pairs(self) -> None:
        self.assertEqual(self.cls("KsKd7c2h", "Qh8d3c"), 2)  # overpair
        self.assertEqual(self.cls("QsJd7c2h", "Qh8d3c"), 2)  # top pair
        self.assertEqual(self.cls("8sJd6c2h", "Qh8d3c"), 1)  # under pair

    def test_playing_the_board_pair_is_not_top_pair(self) -> None:
        self.assertEqual(self.cls("Ad7c9h3s", "KhKd5c"), 0)
        self.assertEqual(self.cls("Kc7c9h3s", "KhKd5c"), 5)  # trips with a hole king
        self.assertEqual(self.cls("Ad7c9h3s", "KhKdKc"), 0)  # board trips

    def test_sets_and_boats(self) -> None:
        self.assertEqual(self.cls("QsQd7c2h", "Qh8d3c"), 5)
        self.assertEqual(self.cls("8s8c7c2h", "Qh8d3c"), 4)
        self.assertEqual(self.cls("QsQd7c2h", "Qh8d8c"), 11)
        self.assertEqual(self.cls("8s3s7c2h", "Qh8d8c3d"), 10)

    def test_straights(self) -> None:
        self.assertEqual(self.cls("JsTd2c2h", "9h8d7c"), 7)  # J-high is the nut straight
        self.assertEqual(self.cls("6s5d2c2h", "9h8d7c"), 6)

    def test_flushes(self) -> None:
        self.assertEqual(self.cls("As2s7c7h", "Ks8s3s"), 9)
        self.assertEqual(self.cls("Qs2s7c7h", "Ks8s3s"), 8)
        # The ace is on the board, so the king is the nut flush card.
        self.assertEqual(self.cls("Ks2s7c7h", "As8s3s"), 9)


class DrawTest(unittest.TestCase):
    def test_flush_draw(self) -> None:
        b = arr("Ks8s3d")
        self.assertEqual(flush_draw(arr("As2s7c7h"), b, 3), 2)
        self.assertEqual(flush_draw(arr("Qs2s7c7h"), b, 3), 1)
        self.assertEqual(flush_draw(arr("Qs2d7c7h"), b, 3), 0)

    def test_straight_draw(self) -> None:
        b = arr("9h8d2c")
        self.assertEqual(straight_draw(arr("JsTd3c3h"), b, 3), 1)  # needs a 7 or a Q
        self.assertEqual(straight_draw(arr("JsTd7c6h"), b, 3), 2)  # wrap
        self.assertEqual(straight_draw(arr("KsKdAcAh"), b, 3), 0)


class LowTest(unittest.TestCase):
    def test_made_low_rank_on_river(self) -> None:
        b = arr("2s5d7hKcQd")
        self.assertEqual(made_low_rank(arr("Ah3dKdKs"), b, 5), 0)  # 7-5-3-2-A nut
        self.assertEqual(made_low_rank(arr("Ah4dKdKs"), b, 5), 1)  # 7-5-4-2-A
        self.assertEqual(made_low_rank(arr("3h4dKdKs"), b, 5), 2)  # 7-5-4-3-2
        self.assertEqual(made_low_rank(arr("Ah6dKdKs"), b, 5), 3)
        self.assertEqual(made_low_rank(arr("KhQhJdTs"), b, 5), 4)

    def test_low_draw_quality(self) -> None:
        b = arr("2s9dKh")
        self.assertEqual(low_draw(arr("Ah3dKdQs"), b, 3), 1)  # A-3 is the nut draw with a deuce on board
        self.assertEqual(low_draw(arr("Ah4dKdQs"), b, 3), 2)
        self.assertEqual(low_draw(arr("7h8dKdQs"), b, 3), 3)
        self.assertEqual(low_draw(arr("2h8dKdQs"), b, 3), 0)  # the deuce is counterfeit

    def test_protection(self) -> None:
        b = arr("2s9dKh")
        self.assertEqual(protected(arr("Ah3d4dQs"), b, 3), 1)
        self.assertEqual(protected(arr("Ah2d3dQs"), b, 3), 0)


class KeyTest(unittest.TestCase):
    def test_keys_are_in_range_and_suit_invariant(self) -> None:
        rng = random.Random(5)
        for _ in range(3000):
            deck = list(range(52))
            rng.shuffle(deck)
            hole, board = np.array(deck[:4]), np.array(deck[4:9])
            perm = rng.sample(range(4), 4)
            relabel = lambda cs: np.array([(c >> 2) * 4 + perm[c & 3] for c in cs])  # noqa: E731
            for n in (3, 4):
                k = early_key(hole, board, n)
                self.assertTrue(0 <= k < EARLY_KEYS)
                self.assertEqual(k, early_key(relabel(hole), relabel(board), n))
            k = river_key(hole, board, omaha_high(hole, board))
            self.assertTrue(0 <= k < RIVER_KEYS)
            self.assertEqual(k, river_key(relabel(hole), relabel(board), omaha_high(relabel(hole), relabel(board))))


if __name__ == "__main__":
    unittest.main()
