from __future__ import annotations

import random
import unittest

import numpy as np

from plo_equity.cards import parse_cards
from plo_premium_proof.fulltree import STREET_BUCKETS, FullTree, FullTreeConfig
from plo_premium_proof.fullkernels import _utility, evaluate_root_actions, tree_links
from plo_premium_proof.kernels import plo_rank
from plo_premium_proof.postflop import (
    best_rank,
    board_distribution,
    flush_draw,
    postflop_bucket,
    strength_bin,
    straight_out_ranks,
)
from plo_premium_proof.solve import thread_seeds
from plo_premium_proof.tables import HandTables, comb_table, five_card_ranks


def cards(text: str) -> np.ndarray:
    return np.asarray(parse_cards(text), dtype=np.int64)


class PostflopFeatureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rank5 = five_card_ranks()
        cls.comb = comb_table()

    def test_best_rank_matches_river_evaluator(self) -> None:
        rng = random.Random(9)
        for _ in range(2000):
            dealt = rng.sample(range(52), 9)
            hole, board = np.asarray(dealt[:4]), np.asarray(dealt[4:])
            self.assertEqual(best_rank(hole, board, 5, self.rank5, self.comb),
                             plo_rank(hole, board, self.rank5, self.comb))

    def test_distribution_counts_every_two_card_holding(self) -> None:
        out = np.empty(1200, dtype=np.int64)
        board = cards("Ts5d2cKhAh")
        self.assertEqual([board_distribution(board, n, self.rank5, self.comb, out) for n in (3, 4, 5)],
                         [1176, 1128, 1081])
        self.assertTrue(np.all(np.diff(out[:1081]) >= 0))

    def test_nut_and_weak_strength(self) -> None:
        out = np.empty(1200, dtype=np.int64)
        board = cards("AsKdQc")
        count = board_distribution(board, 3, self.rank5, self.comb, out)
        nut = best_rank(cards("JhTh3c2d"), board, 3, self.rank5, self.comb)
        weak = best_rank(cards("7h6h3c2d"), board, 3, self.rank5, self.comb)
        self.assertEqual(strength_bin(nut, out, count), 0)
        self.assertEqual(strength_bin(weak, out, count), 9)

    def test_draw_features(self) -> None:
        flop = cards("7s2s9d")
        self.assertEqual(flush_draw(cards("AsKsQh3d"), flop, 3), 2)
        self.assertEqual(flush_draw(cards("QsJs4h3d"), flop, 3), 1)
        self.assertEqual(flush_draw(cards("QhJh4c3d"), flop, 3), 0)
        # 9876 on 5-4-K: a 3, 6, 7 or 8 completes a straight.
        self.assertEqual(straight_out_ranks(cards("9s8h7d6c"), cards("5s4dKc"), 3), 4)

    def test_bucket_ranges(self) -> None:
        out = np.empty(1200, dtype=np.int64)
        rng = random.Random(4)
        for street in (1, 2, 3):
            for _ in range(300):
                dealt = rng.sample(range(52), 9)
                hole, board = np.asarray(dealt[:4]), np.asarray(dealt[4:])
                count = board_distribution(board, street + 2, self.rank5, self.comb, out)
                bucket = postflop_bucket(hole, board, street, out, count, self.rank5, self.comb)
                self.assertTrue(0 <= bucket < STREET_BUCKETS[street])


class FullTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = FullTree.build(FullTreeConfig(stack_bb=20.0))

    def test_shape_and_chip_conservation(self) -> None:
        tree = self.tree
        self.assertEqual(np.bincount(tree.street[tree.actor >= 0]).tolist(), [11213, 39021, 72575, 109449])
        terminal = tree.actor < 0
        totals = tree.behind[terminal].sum(1) + tree.sidepot_amount[terminal].sum(1)
        self.assertTrue(np.allclose(totals, 120.0))
        self.assertLessEqual(int(tree.action_count.max()), 3)

    def test_reproduces_legacy_preflop_tree(self) -> None:
        legacy = FullTree.build(FullTreeConfig(stack_bb=100.0, raise_caps=(2, 0, 0, 0)))
        self.assertEqual(int(np.count_nonzero((legacy.actor >= 0) & (legacy.street == 0))), 5466)

    def test_utility_when_everyone_folds_to_an_open(self) -> None:
        tree = self.tree
        node = int(tree.children[0, 2])  # UTG pot-opens
        while tree.actor[node] >= 0:
            node = int(tree.children[node, 0])  # everyone else folds
        ranks = np.arange(6, dtype=np.int64)
        self.assertAlmostEqual(_utility(node, 0, 20.0, tree.behind, tree.sidepot_count,
                                        tree.sidepot_amount, tree.sidepot_eligible_mask, ranks), 1.5)

    def test_root_evaluation_against_folding_policy(self) -> None:
        tree = self.tree
        tables = HandTables.build()
        policy = np.zeros((tree.rows, 3))
        policy[:, 0] = 1.0  # fold/check first slot everywhere except where hero deviates
        parent, slot, end = tree_links(tree.children, tree.action_count, tree.actor)
        moments = np.zeros((1, 4, 3))
        evaluate_root_actions(
            cards("KcKdAcAd")[None, :], np.asarray([0]), thread_seeds(3, 1), 2,
            tree.first_in_nodes, tables.bucket_of, five_card_ranks(), comb_table(), policy,
            tree.actor, tree.street, tree.decision_index, tree.row_start, tree.action_count,
            tree.behind, tree.sidepot_count, tree.sidepot_amount, tree.sidepot_eligible_mask,
            parent, slot, end, 1e-9, 20.0, moments,
        )
        opens = moments[0, 2, 0] / moments[0, 3, 0]
        self.assertAlmostEqual(opens, 1.5)
        self.assertAlmostEqual(moments[0, 0, 0], 0.0)


if __name__ == "__main__":
    unittest.main()
