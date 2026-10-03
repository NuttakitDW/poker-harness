from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "plo_sizing"))

import sizing  # noqa: E402

from plo_icm.game import Action  # noqa: E402


def opened(open_x, three_f=1.0):
    state = sizing.SizedConfig(stacks=(30.0,) * 6, ante_bb=0.12, open_x=open_x, three_f=three_f,
                               raise_caps=(4, 1, 1, 1)).root()
    return state, state.street_put[0] + state.action_amount(Action.POT)


class SizingRuleTest(unittest.TestCase):
    def test_open_sizes(self):
        for open_x, want in ((2.0, 2.0), (2.5, 2.5), (3.0, 3.0), (sizing.POT, 3.5)):
            with self.subTest(open_x=open_x):
                self.assertAlmostEqual(opened(open_x)[1], want)

    def test_three_bet_fraction_of_a_pot_raise(self):
        for three_f, want in ((1.0, 9.0), (0.5, 5.75), (0.75, 7.375)):
            with self.subTest(three_f=three_f):
                state, _ = opened(2.5, three_f)
                state = state.apply(Action.POT)          # UTG opens to 2.5
                put = state.street_put[1] + state.action_amount(Action.POT)
                self.assertAlmostEqual(put, want)       # pot 4 + call 2.5 -> pot raise by 6.5
                four = state.apply(Action.POT)
                self.assertIn(Action.POT, four.legal_actions())

    def test_four_bets_stay_pot_and_tree_builds(self):
        tree = sizing.FullTree.build(sizing.SizedConfig(stacks=(6.0, 5.0, 8.0), ante_bb=0.1, open_x=2.0,
                                                        three_f=0.5, raise_caps=(3, 0, 0, 0)), cache_dir=None)
        self.assertGreater(tree.node_count, 10)
        self.assertEqual(sizing.size_name(2.5, 0.5), "open 2.5x / 3bet 0.5pot")


if __name__ == "__main__":
    unittest.main()
