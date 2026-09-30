import random
import unittest

from pokerkit import OmahaHoldemHand

from plo_chipev.showdown import precompute_ranks
from plo_equity.cards import card_text, parse_cards
from plo_thesis_audit.evaluator import native_rank, showdown_share
from plo_thesis_audit.payoff import conservative_increment, real_game_increment


def _oracle(hole, board):
    return OmahaHoldemHand.from_game(card_text(hole), card_text(board))


class EvaluatorAndPayoffTest(unittest.TestCase):
    def test_native_exact_two_plus_three_matches_independent_oracle_fixtures(self):
        cases = (
            ("2c3d4h5c", "9c9d8h7h", "AsKsQsJsTs"),
            ("Jh4s8d7c", "AhAd9c9d", "AsKsQs2s3c"),
            ("Ac2d9h8c", "6s7sKhKd", "3s4d5cQhJs"),
            ("AcKd7h6c", "AdKc7s6d", "QsJhTc2c3d"),
        )
        for first_text, second_text, board_text in cases:
            first, second = parse_cards(first_text), parse_cards(second_text)
            board = parse_cards(board_text)
            first_oracle, second_oracle = _oracle(first, board), _oracle(second, board)
            expected = 1.0 if first_oracle > second_oracle else 0.0 if first_oracle < second_oracle else 0.5
            self.assertEqual(showdown_share(first, second, board), expected)


    def test_native_rank_interface_has_exact_parity_with_existing_showdown(self):
        rng = random.Random(912)
        for _ in range(100):
            dealt = rng.sample(range(52), 29)
            holes = tuple(tuple(dealt[4 * seat:4 * seat + 4]) for seat in range(6))
            board = tuple(dealt[24:29])
            text_holes = tuple(
                tuple(card_text(hole)[i:i + 2] for i in range(0, 8, 2))
                for hole in holes
            )
            text_board = tuple(card_text(board)[i:i + 2] for i in range(0, 10, 2))

            existing = precompute_ranks(text_holes, text_board)

            self.assertEqual(tuple(native_rank(hole, board) for hole in holes), existing)


    def test_limp_check_terminal_payoff_identity_matches_real_game(self):
        for share, expected in ((1.0, 1.5), (0.0, -0.5), (0.5, 0.5)):
            with self.subTest(share=share):
                self.assertEqual(conservative_increment("Trash", "check", share), expected)
                self.assertEqual(real_game_increment("check", share), expected)


    def test_limp_fold_to_bb_pot_raise_costs_half_bb_incrementally(self):
        self.assertEqual(conservative_increment("Premium", "pot", None), -0.5)
        self.assertEqual(real_game_increment("pot", None), -0.5)


    def test_trash_bb_cannot_illegally_fold_or_raise_when_check_is_free(self):
        with self.assertRaisesRegex(ValueError, "Trash BB must free-check"):
            conservative_increment("Trash", "pot", None)
