from __future__ import annotations

import unittest

import numpy as np

from o8_fl.evaluator import NO_LOW
from o8_fl.game import BettingState, Rules
from o8_fl.showdown import showdown_net
from o8_fl.tree import FOLD, SHOWDOWN, PublicTree


def play(actions: str, rules: Rules = Rules()) -> BettingState:
    state = BettingState.new(rules)
    for a in actions:
        state = state.apply(a)
    return state


class RulesTest(unittest.TestCase):
    def test_preflop_button_acts_first_and_big_blind_has_option(self) -> None:
        s = BettingState.new()
        self.assertEqual((s.actor, s.legal()), (0, "fcr"))
        s = s.apply("c")  # limp
        self.assertEqual((s.actor, s.street, s.legal()), (1, 0, "kr"))
        s = s.apply("k")
        self.assertEqual((s.actor, s.street, s.legal(), s.committed), (1, 1, "kb", (1.0, 1.0)))

    def test_big_blind_acts_first_after_the_flop(self) -> None:
        s = play("ck")
        self.assertEqual(s.actor, 1)
        s = s.apply("k")
        self.assertEqual((s.actor, s.street), (0, 1))
        s = s.apply("k")
        self.assertEqual((s.actor, s.street), (1, 2))

    def test_bet_sizes_small_then_big(self) -> None:
        s = play("rc")  # 2 BB each preflop
        self.assertEqual(s.committed, (2.0, 2.0))
        s = play("rcbc")  # flop bet 1
        self.assertEqual(s.committed, (3.0, 3.0))
        s = play("rcbcbc")  # turn bet 2
        self.assertEqual(s.committed, (5.0, 5.0))

    def test_five_bet_cap_counts_the_big_blind(self) -> None:
        s = play("rrrr")  # BB, raise, reraise, 4-bet, 5-bet
        self.assertEqual(s.legal(), "fc")
        self.assertEqual(s.committed, (4.0, 5.0))
        flop = play("ck" + "brrrr")
        self.assertEqual(flop.legal(), "fc")

    def test_four_bet_cap(self) -> None:
        self.assertEqual(play("rrr", Rules(cap=4)).legal(), "fc")

    def test_most_one_player_can_lose(self) -> None:
        capped = "rrrrc" + "brrrrc" * 3
        self.assertEqual(play(capped).committed, (30.0, 30.0))
        self.assertTrue(play(capped).terminal)
        four = "rrrc" + "brrrc" * 3
        self.assertEqual(play(four, Rules(cap=4)).committed, (24.0, 24.0))

    def test_fold_and_showdown_are_terminal(self) -> None:
        s = play("f")
        self.assertEqual((s.terminal, s.folder), (True, 0))
        s = play("ck" + "kk" * 3)
        self.assertEqual((s.terminal, s.folder, s.committed), (True, None, (1.0, 1.0)))

    def test_illegal_action_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BettingState.new().apply("k")
        with self.assertRaises(ValueError):
            play("rrrr").apply("r")


class ShowdownTest(unittest.TestCase):
    def test_scoop(self) -> None:
        self.assertEqual(showdown_net(4.0, 10, 5, 100, 200), 4.0)

    def test_no_low_high_takes_all(self) -> None:
        self.assertEqual(showdown_net(4.0, 5, 10, NO_LOW, NO_LOW), -4.0)

    def test_split_high_and_low(self) -> None:
        self.assertEqual(showdown_net(4.0, 10, 5, 200, 100), 0.0)

    def test_quartered(self) -> None:
        # Player 0 wins high and ties low: 3/4 of an 8 pot = 6, net +2.
        self.assertEqual(showdown_net(4.0, 10, 5, 100, 100), 2.0)

    def test_only_one_low_qualifies(self) -> None:
        self.assertEqual(showdown_net(4.0, 5, 10, 100, NO_LOW), 0.0)


class TreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = PublicTree.build(Rules())

    def test_every_line_is_reachable_and_unmerged(self) -> None:
        t = self.tree
        self.assertEqual(len(t.histories), t.node_count)
        self.assertEqual(len(set(t.histories)), t.node_count)
        self.assertEqual(t.node_count, t.decision_count + int(np.count_nonzero(t.kind != 0)))

    def test_terminal_payoffs(self) -> None:
        t = self.tree
        fold = t.history_to_node["rf"]
        self.assertEqual((t.kind[fold], t.folder[fold]), (FOLD, 1))
        np.testing.assert_allclose(t.committed[fold], (2.0, 1.0))
        show = t.history_to_node["ck" + "kk" * 3]
        self.assertEqual(t.kind[show], SHOWDOWN)

    def test_children_follow_action_slots(self) -> None:
        t = self.tree
        root = 0
        self.assertEqual(t.histories[t.children[root, 0]], "f")
        self.assertEqual(t.histories[t.children[root, 1]], "c")
        self.assertEqual(t.histories[t.children[root, 2]], "r")
        self.assertEqual(t.street[t.history_to_node["ck"]], 1)

    def test_max_commitment(self) -> None:
        self.assertEqual(float(self.tree.committed.max()), 30.0)


if __name__ == "__main__":
    unittest.main()
