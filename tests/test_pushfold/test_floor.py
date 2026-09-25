"""M3: the Spot (who sits where with what) and the Floor (who may act after what)."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import floor  # noqa: E402
from pushfold.spot import Spot, SpotError  # noqa: E402


class SpotTest(unittest.TestCase):
    def test_names_by_table_size(self):
        self.assertEqual(Spot((10, 10)).names, ("SB", "BB"))
        self.assertEqual(Spot((10,) * 3).names, ("BTN", "SB", "BB"))
        self.assertEqual(Spot((10,) * 6).names, ("UTG", "HJ", "CO", "BTN", "SB", "BB"))
        self.assertEqual(Spot((10,) * 9).names[:4], ("UTG", "UTG+1", "UTG+2", "LJ"))

    def test_posts(self):
        spot = Spot((10, 10, 10), ante=0.1)
        self.assertEqual(spot.blinds, (0.0, 0.5, 1.0))
        self.assertEqual(spot.antes, (0.1, 0.1, 0.1))
        bb_ante = Spot((10, 10, 10), ante=1.0, ante_mode="bb")
        self.assertEqual(bb_ante.antes, (0.0, 0.0, 1.0))

    def test_validation(self):
        bad = [
            dict(stacks=(10,)),
            dict(stacks=(10,) * 10),
            dict(stacks=(10, -1)),
            dict(stacks=(10, math.nan)),
            dict(stacks=(10, 0.9)),                        # BB cannot cover the big blind
            dict(stacks=(10, 10), ante=-0.1),
            dict(stacks=(10, 10), ante_mode="button"),
            dict(stacks=(10, 10), sb=2.0),                 # small blind bigger than big blind
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(SpotError):
                Spot(**kwargs)


def expected_terminals(n: int, cap: int = 3) -> int:
    return 1 + (n - 1) + sum(math.comb(n, k) for k in range(2, cap + 1))


class FloorTest(unittest.TestCase):
    def test_heads_up_tree(self):
        tree = floor.build(Spot((10, 10)))
        self.assertEqual([(n.seat, n.history) for n in tree.nodes], [(0, ()), (1, (1,))])
        self.assertEqual(sorted(t.actions for t in tree.terminals),
                         [(0, 2), (1, 0), (1, 1)])

    def test_three_handed_tree(self):
        tree = floor.build(Spot((10, 10, 10)))
        self.assertEqual(len(tree.nodes), 6)
        self.assertEqual(len(tree.terminals), 7)

    def test_nine_handed_counts_with_three_way_cap(self):
        for n in range(2, 10):
            tree = floor.build(Spot((10,) * n))
            self.assertEqual(len(tree.terminals), expected_terminals(n), n)
            self.assertTrue(all(len(t.jammers) <= 3 for t in tree.terminals))

    def test_every_seat_acts_at_most_once_and_node_links_are_consistent(self):
        tree = floor.build(Spot((10,) * 6))
        for terminal in tree.terminals:
            for seat, action in enumerate(terminal.actions):
                node = terminal.nodes[seat]
                if action == floor.IDLE:
                    self.assertEqual(node, -1)
                else:
                    self.assertEqual(tree.nodes[node].seat, seat)
                    self.assertEqual(tree.nodes[node].history, terminal.actions[:seat])

    def test_labels(self):
        tree = floor.build(Spot((10, 10, 10)))
        self.assertEqual(tree.nodes[0].labels, ("fold", "shove"))
        facing = [n for n in tree.nodes if 1 in n.history][0]
        self.assertEqual(facing.labels, ("fold", "call"))

    def test_walk_goes_to_the_big_blind(self):
        tree = floor.build(Spot((10,) * 4))
        walk = [t for t in tree.terminals if not t.jammers][0]
        self.assertEqual(walk.alive, (3,))


if __name__ == "__main__":
    unittest.main()
