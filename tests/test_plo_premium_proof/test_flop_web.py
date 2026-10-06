"""The PLO4 page's flop data: bucket tables per flop and the flop tree behind the preflop lines."""

from __future__ import annotations

import unittest

import numpy as np

from plo_premium_proof.flop_web import LETTER, NO_BUCKET, flop_buckets, flop_tree, parse_board
from plo_premium_proof.fullsolve import tree_config
from plo_premium_proof.fulltree import STREET_BUCKETS, FullTree
from plo_premium_proof.tables import comb_table, five_card_ranks


class FlopWebTest(unittest.TestCase):
    def test_board_cards_have_no_bucket_and_the_rest_fit_the_flop_buckets(self) -> None:
        board = parse_board("AsKd7c")
        hands = np.asarray([[48, 49, 50, 51], [20, 0, 1, 2], [16, 17, 18, 19]], dtype=np.int64)  # aces, 7c+deuces, sixes
        buckets = flop_buckets(hands, board, five_card_ranks(), comb_table())
        self.assertEqual(buckets[0], NO_BUCKET)
        self.assertEqual(buckets[1], NO_BUCKET)
        self.assertLess(buckets[2], STREET_BUCKETS[1])

    def test_flop_roots_follow_heads_up_preflop_lines(self) -> None:
        config = tree_config(10.0, (4, 2, 2, 2), 0.116, seats=2, ante_on_top=True)
        tree = FullTree.build(config, cache_dir=None)
        nodes, roots, order = flop_tree(tree, config.root())
        self.assertIn("ck", roots)  # SB limps, BB checks: the flop starts
        self.assertEqual(len(nodes), len(order))
        self.assertTrue(all(tree.street[node] == 1 for node in order))
        self.assertLessEqual(set("".join(roots)), set(LETTER.values()))
        for node in nodes:
            for option in node["options"]:
                self.assertTrue(option["child"] >= 0 or option["end"] in ("turn", "hand over"))


if __name__ == "__main__":
    unittest.main()
