import random
import unittest

from plo_chipev.game import PreflopState
from plo_chipev.showdown import precompute_ranks, settle_by_ranks
from plo_icm.cards import deal
from plo_icm.game import Action, settle


def play(state, *actions):
    for action in actions:
        state = state.apply(action)
    return state


class GameTest(unittest.TestCase):
    def test_pot_open_and_three_bet_sizes_and_four_bet_is_blocked(self):
        state = PreflopState.new()
        self.assertEqual(state.legal_actions(), (Action.FOLD, Action.CALL, Action.POT))
        self.assertAlmostEqual(state.action_amount(Action.POT), 3.5)

        state = state.apply(Action.POT)
        self.assertEqual(state.raises, 1)
        self.assertAlmostEqual(state.action_amount(Action.POT), 12.0)
        state = state.apply(Action.POT)

        self.assertEqual(state.raises, 2)
        self.assertEqual(state.legal_actions(), (Action.FOLD, Action.CALL))


    def test_limp_iso_and_squeeze_are_the_only_two_raises(self):
        state = play(PreflopState.new(), Action.CALL)
        self.assertAlmostEqual(state.action_amount(Action.POT), 4.5)
        state = play(state, Action.POT, Action.CALL)

        self.assertEqual(state.raises, 1)
        self.assertIn(Action.POT, state.legal_actions())
        squeezed = state.apply(Action.POT)
        self.assertEqual(squeezed.raises, 2)
        self.assertNotIn(Action.POT, squeezed.legal_actions())


    def test_big_blind_has_free_check_after_a_limp_and_check_ends_decisions(self):
        state = play(
            PreflopState.new(),
            Action.CALL,
            Action.FOLD,
            Action.FOLD,
            Action.FOLD,
            Action.FOLD,
        )

        self.assertEqual(state.actor, 5)
        self.assertEqual(state.legal_actions(), (Action.CHECK, Action.POT))
        state = state.apply(Action.CHECK)
        self.assertTrue(state.terminal)
        self.assertEqual(state.street, 1)
        self.assertEqual(state.legal_actions(), ())


    def test_preflop_closure_skips_all_postflop_decisions(self):
        state = play(
            PreflopState.new(),
            Action.POT,
            Action.FOLD,
            Action.FOLD,
            Action.FOLD,
            Action.FOLD,
            Action.CALL,
        )

        self.assertEqual(state.street, 1)
        self.assertTrue(state.terminal)
        self.assertFalse(state.base.terminal)
        self.assertEqual(state.legal_actions(), ())


    def test_rank_settlement_matches_legacy_across_sidepots_folds_and_ties(self):
        rng = random.Random(731)
        for _ in range(100):
            holes, board = deal(rng)
            ranks = precompute_ranks(holes, board)
            committed = tuple(rng.choice((0.5, 1.0, 4.0, 12.0, 100.0)) for _ in range(6))
            keep_live = committed.index(max(committed))
            foldable = [seat for seat in range(6) if seat != keep_live]
            folded = frozenset(rng.sample(foldable, rng.randrange(5)))
            behind = tuple(100.0 - amount for amount in committed)

            expected = settle(behind, committed, folded, holes, board)
            actual = settle_by_ranks(behind, committed, folded, ranks)
            for got, want in zip(actual, expected):
                self.assertAlmostEqual(got, want)
            self.assertAlmostEqual(sum(actual), 600.0)


    def test_rank_settlement_splits_exact_ties_and_conserves_chips(self):
        behind = (98.0, 95.0, 95.0)
        committed = (2.0, 5.0, 5.0)
        ranks = (10, 10, 20)

        final = settle_by_ranks(behind, committed, frozenset(), ranks)

        for got, want in zip(final, (101.0, 104.0, 95.0)):
            self.assertAlmostEqual(got, want)
        self.assertAlmostEqual(sum(final), 300.0)


    def test_native_rank_uses_exactly_two_hole_cards_and_three_board_cards(self):
        board = ("As", "Ks", "Qs", "Js", "2d")
        holes = (
            ("Ts", "9c", "8h", "7d"),
            ("6s", "5s", "Ah", "Ad"),
            ("2c", "3c", "4d", "5d"),
            ("3h", "4h", "6h", "7h"),
            ("8c", "9d", "Th", "Jh"),
            ("Qc", "Qd", "Kc", "Kd"),
        )

        ranks = precompute_ranks(holes, board)
        self.assertLess(ranks[1], ranks[0])
