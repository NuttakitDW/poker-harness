import unittest
import random

from plo_icm.cards import canonical_cards, deal, parse_cards, winners
from plo_icm.game import Action, PLOState, settle


class CardsTest(unittest.TestCase):
    def test_canonical_cards_ignore_hole_order_and_suit_names(self):
        a = canonical_cards(("As", "Ks", "Qd", "Jd"), ("2c", "3h", "4c"))
        b = canonical_cards(("Jc", "Ah", "Kh", "Qc"), ("4s", "2s", "3d"))
        self.assertEqual(a, b)

    def test_turn_and_river_order_remains_public_information(self):
        hole = ("As", "Ks", "Qd", "Jd")
        self.assertNotEqual(canonical_cards(hole, ("2c", "3h", "4c", "5d", "6s")),
                            canonical_cards(hole, ("2c", "3h", "4c", "6s", "5d")))

    def test_omaha_uses_exactly_two_hole_and_three_board(self):
        board = ("As", "Ks", "Qs", "Js", "2d")
        # A Hold'em-like evaluator would give seat 0 a royal with one hole card. PLO's
        # exact-two rule gives seat 1 the ace-high flush over seat 0's king-high straight.
        holes = (("Ts", "9c", "8h", "7d"), ("6s", "5s", "Ah", "Ad"))
        self.assertEqual(winners(holes, board), (1,))

    def test_duplicate_cards_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            winners((("As", "As", "Kd", "Qc"),), ("2c", "3c", "4c", "5c", "6c"))

    def test_malformed_partial_card_is_rejected(self):
        for bad in ("A", ["Asgarbage"], ["A"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_cards(bad)


class BettingTest(unittest.TestCase):
    def test_two_bb_first_raise_amounts_from_utg_sb_and_bb(self):
        utg = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        self.assertIn(Action.RAISE_2BB, utg.legal_actions())
        self.assertNotIn(Action.POT, utg.legal_actions())
        self.assertAlmostEqual(utg.action_amount(Action.RAISE_2BB), 2)
        utg = utg.apply(Action.RAISE_2BB)
        self.assertEqual(utg.history[-1], "0:0:raise_2bb:2")

        sb = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        for _ in range(4):
            sb = sb.apply(Action.FOLD)
        self.assertEqual(sb.actor, 4)
        self.assertAlmostEqual(sb.action_amount(Action.RAISE_2BB), 1.5)

        bb = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        for action in (Action.CALL, Action.FOLD, Action.FOLD, Action.FOLD, Action.FOLD):
            bb = bb.apply(action)
        self.assertEqual(bb.actor, 5)
        self.assertAlmostEqual(bb.action_amount(Action.RAISE_2BB), 1)
        self.assertNotIn(Action.POT, bb.legal_actions())

    def test_pot_three_bet_remains_after_two_bb_open(self):
        state = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        state = state.apply(Action.RAISE_2BB)
        self.assertNotIn(Action.RAISE_2BB, state.legal_actions())
        self.assertIn(Action.POT, state.legal_actions())
        self.assertAlmostEqual(state.street_put[state.actor] + state.action_amount(Action.POT), 7.5)

    def test_two_bb_is_first_raise_only_and_never_postflop(self):
        state = PLOState.new((10,) * 6, ante=0, ante_mode="individual")
        state = state.apply(Action.RAISE_2BB)
        self.assertNotIn(Action.RAISE_2BB, state.legal_actions())
        for action in (Action.FOLD,) * 4 + (Action.CALL,):
            state = state.apply(action)
        self.assertEqual(state.street, 1)
        self.assertNotIn(Action.RAISE_2BB, state.legal_actions())

    def test_short_two_bb_allin_has_no_duplicate_pot_branch(self):
        state = PLOState.new((1.5, 10, 10, 10, 10, 10), ante=0, ante_mode="individual")
        self.assertIn(Action.RAISE_2BB, state.legal_actions())
        self.assertNotIn(Action.POT, state.legal_actions())
        self.assertAlmostEqual(state.action_amount(Action.RAISE_2BB), 1.5)
        raised = state.apply(Action.RAISE_2BB)
        self.assertAlmostEqual(raised.current_bet, 1.5)
        self.assertAlmostEqual(raised.min_raise, 1)

    def test_nominal_bb_bringin_when_bb_is_short(self):
        s = PLOState.new((10, 10, 10, 10, 10, .25), ante=0, ante_mode="individual")
        self.assertAlmostEqual(s.action_amount(Action.CALL), 1.0)
        self.assertAlmostEqual(s.action_amount(Action.POT), 3.5)

    def test_preflop_pot_caps_exclude_antes(self):
        s = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        self.assertAlmostEqual(s.action_amount(Action.POT), 3.5)
        for _ in range(4):
            s = s.apply(Action.FOLD)
        self.assertEqual(s.actor, 4)
        self.assertAlmostEqual(s.street_put[s.actor] + s.action_amount(Action.POT), 3.0)

    def test_postflop_pot_includes_antes_and_streets_advance(self):
        s = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        for action in (Action.FOLD,) * 4 + (Action.CALL, Action.CHECK):
            s = s.apply(action)
        self.assertEqual(s.street, 1)
        self.assertEqual(s.actor, 4)
        self.assertAlmostEqual(s.action_amount(Action.POT), 2.6)
        self.assertIn(Action.POT, s.legal_actions())
        s = s.apply(Action.POT)
        self.assertAlmostEqual(s.street_put[4], 2.6)

    def test_bb_has_option_after_limp(self):
        s = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        for action in (Action.CALL, Action.FOLD, Action.FOLD, Action.FOLD, Action.FOLD):
            s = s.apply(action)
        self.assertEqual(s.actor, 5)
        self.assertIn(Action.CHECK, s.legal_actions())
        self.assertIn(Action.RAISE_2BB, s.legal_actions())
        self.assertNotIn(Action.POT, s.legal_actions())

    def test_betting_is_available_on_every_postflop_street(self):
        s = PLOState.new((10,) * 6, ante=0, ante_mode="individual")
        for action in (Action.FOLD,) * 4 + (Action.CALL, Action.CHECK):
            s = s.apply(action)
        for action in (Action.POT, Action.CALL, Action.CHECK, Action.POT, Action.CALL,
                       Action.POT, Action.CALL):
            self.assertIn(action, s.legal_actions())
            s = s.apply(action)
        self.assertTrue(s.terminal)

    def test_short_allin_does_not_reopen(self):
        s = PLOState.new((10, 10, 10, 10, 1.5, 10), ante=0, ante_mode="individual")
        s = s.apply(Action.CALL)
        for _ in range(3):
            s = s.apply(Action.FOLD)
        s = s.apply(Action.RAISE_2BB)  # SB all-in short raise from 1 to 1.5
        s = s.apply(Action.CALL)
        self.assertEqual(s.actor, 0)
        self.assertNotIn(Action.POT, s.legal_actions())

    def test_cumulative_short_allins_reopen(self):
        s = PLOState.new((10, 4.5, 6, 10, 10, 10), ante=0, ante_mode="individual",
                         opening_raise_mode="pot_only")
        for action in (Action.POT, Action.POT, Action.POT, Action.CALL, Action.FOLD, Action.FOLD):
            s = s.apply(action)
        self.assertEqual(s.actor, 0)
        self.assertIn(Action.POT, s.legal_actions())

    def test_short_big_blind_posts_live_blind_before_bba(self):
        s = PLOState.new((10, 10, 10, 10, 10, .5), ante=1, ante_mode="bb")
        self.assertEqual(s.committed[5], .5)
        self.assertEqual(s.dead_money, 0)

    def test_no_dry_sidepot_betting(self):
        s = PLOState.new((10, .1, .1, .1, .1, .5), ante=.1, ante_mode="individual")
        self.assertFalse(s.terminal)
        self.assertEqual(s.legal_actions(), (Action.FOLD, Action.CALL))
        s = s.apply(Action.CALL)
        self.assertTrue(s.terminal)

    def test_big_blind_ante_is_dead_main_pot_money(self):
        s = PLOState.new((10,) * 6, ante=1, ante_mode="bb")
        for action in (Action.CALL, Action.FOLD, Action.FOLD, Action.FOLD, Action.FOLD, Action.CHECK):
            s = s.apply(action)
        holes = (("As", "Ad", "3c", "4c"), ("2h", "2c", "5c", "6c"),
                 ("3h", "3d", "5d", "6d"), ("4h", "4d", "5h", "6h"),
                 ("5s", "6s", "7s", "8s"), ("Js", "Jd", "Tc", "9c"))
        out = settle(s.behind, s.committed, s.folded, holes,
                     ("2s", "7d", "8c", "Qh", "Kd"), s.dead_money)
        self.assertAlmostEqual(out[0], 12.5)

    def test_sidepots_ties_and_conservation(self):
        committed = (2.0, 5.0, 5.0)
        holes = (("As", "Ad", "3c", "4c"), ("Ah", "Ac", "5c", "6c"), ("Js", "Jd", "Tc", "9c"))
        out = settle((0, 0, 0), committed, frozenset(), holes, ("2s", "7d", "8c", "Qh", "Kd"))
        self.assertAlmostEqual(sum(out), sum(committed))
        self.assertEqual(out, (3.0, 9.0, 0.0))

    def test_seeded_random_legal_play_terminates_and_conserves_chips(self):
        rng = random.Random(11)
        saw_postflop_bet = False
        for _ in range(100):
            stacks = tuple(rng.uniform(.2, 10) for _ in range(6))
            state = PLOState.new(stacks, ante=.1, ante_mode="individual")
            steps = 0
            while not state.terminal:
                legal = state.legal_actions()
                self.assertTrue(legal)
                action = rng.choice(legal)
                saw_postflop_bet |= state.street > 0 and action == Action.POT
                state = state.apply(action)
                steps += 1
                self.assertLess(steps, 100)
            holes, board = deal(rng)
            final = settle(state.behind, state.committed, state.folded, holes, board, state.dead_money)
            self.assertAlmostEqual(sum(final), sum(stacks), places=7)
        self.assertTrue(saw_postflop_bet)


if __name__ == "__main__":
    unittest.main()
