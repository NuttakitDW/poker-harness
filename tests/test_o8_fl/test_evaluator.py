from __future__ import annotations

import itertools
import random
import unittest

import numpy as np
from phevaluator import evaluate_cards, evaluate_omaha_cards

from o8_fl.cards import card_id, card_ids, card_text
from o8_fl.evaluator import (FLUSH5, LOW5, NO_LOW, PLAIN5, high5, low5, omaha_high, omaha_high_prepared, omaha_low,
                             omaha_low_prepared, prepare_board)

LOW_VALUE = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8}


def reference_low(hole: list[str], board: list[str]) -> tuple[int, ...] | None:
    """Brute force: exactly two hole cards and three board cards, five distinct ranks of 8 or lower."""
    best = None
    for two in itertools.combinations(hole, 2):
        for three in itertools.combinations(board, 3):
            ranks = [c[0] for c in two + three]
            if any(r not in LOW_VALUE for r in ranks) or len(set(ranks)) != 5:
                continue
            key = tuple(sorted((LOW_VALUE[r] for r in ranks), reverse=True))
            best = key if best is None or key < best else best
    return best


def random_deal(rng: random.Random, n: int) -> list[str]:
    return rng.sample([card_text(i) for i in range(52)], n)


class CardTest(unittest.TestCase):
    def test_ids_match_phevaluator_order(self) -> None:
        self.assertEqual(card_id("2c"), 0)
        self.assertEqual(card_id("2s"), 3)
        self.assertEqual(card_id("As"), 51)
        self.assertEqual([card_text(i) for i in card_ids("AhKd")], ["Ah", "Kd"])

    def test_bad_cards_are_rejected(self) -> None:
        for text in ("1c", "Ax", "AhAh", "Ah K"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                card_ids(text)


class HighTest(unittest.TestCase):
    def test_five_card_order_matches_phevaluator(self) -> None:
        rng = random.Random(7)
        hands = [random_deal(rng, 5) for _ in range(3000)]
        hands += [["As", "2d", "3h", "4c", "5s"], ["6s", "2d", "3h", "4c", "5s"], ["As", "Kd", "Qh", "Jc", "Ts"]]
        mine = [high5(*card_ids("".join(h))) for h in hands]
        theirs = [evaluate_cards(*h) for h in hands]  # smaller is stronger
        for i in range(0, len(hands) - 1):
            a, b = i, i + 1
            with self.subTest(a=hands[a], b=hands[b]):
                self.assertEqual(np.sign(mine[a] - mine[b]), -np.sign(theirs[a] - theirs[b]))

    def test_omaha_high_matches_phevaluator(self) -> None:
        rng = random.Random(11)
        for _ in range(1500):
            cards = random_deal(rng, 13)
            board, a, b = cards[:5], cards[5:9], cards[9:]
            mine = np.sign(omaha_high(np.array(card_ids("".join(a))), np.array(card_ids("".join(board))))
                           - omaha_high(np.array(card_ids("".join(b))), np.array(card_ids("".join(board)))))
            theirs = -np.sign(evaluate_omaha_cards(*board, *a) - evaluate_omaha_cards(*board, *b))
            self.assertEqual(mine, theirs, (board, a, b))

    def test_must_use_two_hole_cards(self) -> None:
        board = np.array(card_ids("AsKsQsJs2d"))
        one_spade = np.array(card_ids("Th3c4c5c"))
        # Four spades and A-K-Q-J on board, but with exactly two hole cards neither a flush nor a straight is possible.
        self.assertLess(omaha_high(one_spade, board), high5(*card_ids("AsKsQsJsTs")))


class LowTest(unittest.TestCase):
    def test_wheel_is_the_best_low_and_straights_do_not_hurt(self) -> None:
        self.assertLess(low5(*card_ids("As2d3h4c5s")), low5(*card_ids("As2d3h4c6s")))
        self.assertLess(low5(*card_ids("6s4d3h2cAs")), low5(*card_ids("7s4d3h2cAs")))

    def test_no_low_with_pair_or_nine(self) -> None:
        self.assertEqual(low5(*card_ids("As2d3h4c4s")), NO_LOW)
        self.assertEqual(low5(*card_ids("9s2d3h4c5s")), NO_LOW)

    def test_omaha_low_matches_brute_force(self) -> None:
        rng = random.Random(3)
        for _ in range(4000):
            cards = random_deal(rng, 9)
            board, hole = cards[:5], cards[5:]
            ref = reference_low(hole, board)
            mine = omaha_low(np.array(card_ids("".join(hole))), np.array(card_ids("".join(board))))
            if ref is None:
                self.assertEqual(mine, NO_LOW, (hole, board))
            else:
                self.assertNotEqual(mine, NO_LOW, (hole, board))
                self.assertEqual(mine, low5(*card_ids("".join(
                    {1: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8"}[v] + s
                    for v, s in zip(ref, "cdhsc")))), (hole, board))

    def test_board_with_two_low_cards_gives_no_low(self) -> None:
        board = np.array(card_ids("AsKdQh2cJs"))
        self.assertEqual(omaha_low(np.array(card_ids("3c4c5d6d")), board), NO_LOW)

    def test_counterfeit(self) -> None:
        # A-2 is counterfeited when the board pairs the deuce: best low uses A-3 from hand only if held.
        board = np.array(card_ids("2s4d7hKc2c"))
        a2 = omaha_low(np.array(card_ids("Ad2dQsQh")), board)
        a3 = omaha_low(np.array(card_ids("Ac3cJsJh")), board)
        self.assertLess(a3, a2)


class PreparedTest(unittest.TestCase):
    def _check(self, hole: np.ndarray, board: np.ndarray) -> None:
        ranks, suit = np.empty((10, 3), dtype=np.int64), np.empty(10, dtype=np.int64)
        mask, low = np.empty(10, dtype=np.int64), np.empty(10, dtype=np.int64)
        prepare_board(board, ranks, suit, mask, low)
        self.assertEqual(omaha_high_prepared(hole, ranks, suit, mask, PLAIN5, FLUSH5), omaha_high(hole, board))
        self.assertEqual(omaha_low_prepared(hole, low, LOW5), omaha_low(hole, board))

    def test_prepared_evaluation_equals_the_direct_one(self) -> None:
        rng = np.random.default_rng(4)
        for _ in range(20000):
            cards = rng.permutation(52)[:9].astype(np.int64)
            self._check(cards[:4], cards[4:])

    def test_prepared_evaluation_on_flush_and_paired_boards(self) -> None:
        for hole, board in (("AsKs2d3d", "QsJsTs4d5d"), ("9s8s7h6h", "5s4s3s3h3d"), ("AhAd2h2d", "AsAc2s9h9d"),
                            ("5h4h3c2c", "Ah6h7hKcKd"), ("KsQs2s3s", "AsJsTs9s8s")):
            with self.subTest(hole=hole, board=board):
                self._check(np.array(card_ids(hole), dtype=np.int64), np.array(card_ids(board), dtype=np.int64))


if __name__ == "__main__":
    unittest.main()
