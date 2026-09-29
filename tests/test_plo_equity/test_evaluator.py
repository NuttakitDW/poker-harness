import random
import unittest

from pokerkit import OmahaHoldemHand

from plo_equity.cards import card_text
from plo_equity.evaluator import evaluate, showdown_share


def oracle(hole, board):
    return OmahaHoldemHand.from_game(card_text(hole), card_text(board))


class EvaluatorTest(unittest.TestCase):
    def test_native_order_matches_pokerkit_random_oracle(self):
        rng = random.Random(2909)
        for _ in range(1_000):
            dealt = rng.sample(range(52), 13)
            board, first, second = dealt[:5], dealt[5:9], dealt[9:13]
            native = (evaluate(first, board) < evaluate(second, board)) - (
                evaluate(first, board) > evaluate(second, board))
            reference = (oracle(first, board) > oracle(second, board)) - (
                oracle(first, board) < oracle(second, board))
            self.assertEqual(native, reference)

    def test_omaha_traps_match_pokerkit(self):
        cases = (
            ("2c3d4h5c", "9c9d8h7h", "AsKsQsJsTs"),  # board royal cannot play
            ("Jh4s8d7c", "AhAd9c9d", "AsKsQs2s3c"),  # one hole spade is not a flush
            ("Ac2d9h8c", "6s7sKhKd", "3s4d5cQhJs"),  # wheel using exactly two
            ("AcKd7h6c", "AdKc7s6d", "QsJhTc2c3d"),  # exact tie
        )
        from plo_equity.cards import parse_cards
        for first, second, shown in cases:
            holes = (parse_cards(first), parse_cards(second))
            board = parse_cards(shown)
            native = showdown_share(holes, board)
            a, b = oracle(holes[0], board), oracle(holes[1], board)
            expected = (1.0, 0.0) if a > b else (0.0, 1.0) if b > a else (0.5, 0.5)
            self.assertEqual(native, expected)

    def test_invalid_native_inputs_are_rejected_before_c_call(self):
        for hole, board in (((-1, 1, 2, 3), (4, 5, 6, 7, 8)),
                            ((True, 1, 2, 3), (4, 5, 6, 7, 8)),
                            ((0, 1, 2, 3), (4, 5, 6, 7, 52))):
            with self.subTest(hole=hole, board=board), self.assertRaises(ValueError):
                evaluate(hole, board)

    def test_duplicate_cards_between_opponents_are_rejected(self):
        with self.assertRaises(ValueError):
            showdown_share(((0, 1, 2, 3), (0, 5, 6, 7)), (8, 9, 10, 11, 12))
        with self.assertRaises(ValueError):
            showdown_share((), (8, 9, 10, 11, 12))
