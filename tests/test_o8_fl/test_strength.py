from __future__ import annotations

import unittest

import numpy as np

from o8_fl.cards import card_ids
from o8_fl.strength import COUNTS, NO_LOW, board_buckets, deal_buckets, low5, low_distribution, low_grade
from plo_premium_proof.tables import comb_table, five_card_ranks


def ids(text: str) -> np.ndarray:
    return np.asarray(card_ids(text), dtype=np.int64)


class StrengthTest(unittest.TestCase):
    def test_low5_orders_lows_and_rejects_pairs_and_high_cards(self) -> None:
        wheel = low5(*ids("As2d3h4c5s"))
        eight = low5(*ids("8s7d6h5c4s"))
        self.assertLess(wheel, low5(*ids("As2d3h4c6s")))
        self.assertLess(low5(*ids("8s5d4h3c2s")), low5(*ids("8s6d4h3c2s")))
        self.assertLess(wheel, eight)
        self.assertEqual(low5(*ids("As2d3h4c4s")), NO_LOW)
        self.assertEqual(low5(*ids("As2d3h4c9s")), NO_LOW)

    def grade(self, hole: str, board: str) -> int:
        board_ids = ids(board)
        dist = np.empty(1326, dtype=np.int64)
        count = low_distribution(board_ids, len(board_ids), dist)
        return int(low_grade(ids(hole), board_ids, len(board_ids), dist, count))

    def test_low_grades(self) -> None:
        self.assertEqual(self.grade("As2dKhKc", "3h4c5sQdJh"), 4)  # nut low
        self.assertEqual(self.grade("AsKdKhQc", "3h4c5sQdJh"), 0)  # one low card: no low
        self.assertEqual(self.grade("As2dKhKc", "TcJdQh9sKs"), 0)  # board has no low
        self.assertEqual(self.grade("As2dKhKc", "7cKdQh"), 3)  # draw to the nut low on the flop
        self.assertEqual(self.grade("4s6dKhKc", "7cKdQh"), 1)  # weak draw
        self.assertEqual(self.grade("As2dKhKc", "TcKdQh"), 0)  # no low card on the flop: too late
        self.assertEqual(self.grade("7s8dKhKc", "As2d3hQdJh"), 1)  # 8-7 low with many better

    def test_buckets_stay_in_range(self) -> None:
        rng = np.random.default_rng(3)
        cards = np.array([rng.permutation(52)[:13] for _ in range(300)], dtype=np.uint8)
        buckets = deal_buckets(cards, five_card_ranks(), comb_table())
        for street, count in enumerate(COUNTS):
            self.assertLess(int(buckets[:, :, street].max()), count)
        table = board_buckets(cards[:50, :4].astype(np.int64), cards[0, 8:13].astype(np.int64), 3,
                              five_card_ranks(), comb_table())
        self.assertTrue(all(b == 65535 or b < COUNTS[2] for b in table))


if __name__ == "__main__":
    unittest.main()
