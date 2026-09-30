from __future__ import annotations

import random
import unittest

import numpy as np
from phevaluator import _pheval

from plo_chipev_fast.tree import ACTION_IDS
from plo_premium_proof.kernels import _deal, plo_rank, train_batch
from plo_premium_proof.tables import (
    HandTables,
    TreeArrays,
    colex_index,
    comb_table,
    five_card_ranks,
    hand_classes,
)
from plo_premium_proof.verify import _ratio, run_tasks, verdict, Estimate


def _passive_policy(tree: TreeArrays, buckets: int) -> np.ndarray:
    """Everyone folds when allowed, otherwise checks, otherwise calls."""
    policy = np.zeros((tree.decision_count, buckets, 3))
    for node in np.flatnonzero(tree.actor >= 0):
        ids = list(tree.action_ids[node, : tree.action_count[node]])
        for wanted in (ACTION_IDS["fold"], ACTION_IDS["check"], ACTION_IDS["call"]):
            if wanted in ids:
                policy[tree.decision_index[node], :, ids.index(wanted)] = 1.0
                break
    return policy


class ProofTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = HandTables.build()
        cls.tree = TreeArrays.build()
        cls.rank5 = five_card_ranks()
        cls.comb = comb_table()

    def test_plo_rank_matches_phevaluator(self) -> None:
        rng = random.Random(3)
        for _ in range(3000):
            cards = rng.sample(range(52), 9)
            hole, board = np.asarray(cards[:4]), np.asarray(cards[4:])
            expected = _pheval.evaluate_plo4_cards(*cards[4:], *cards[:4])
            self.assertEqual(plo_rank(hole, board, self.rank5, self.comb), expected)

    def test_buckets_never_mix_tiers(self) -> None:
        self.assertTrue(self.tables.tier_is_pure())
        self.assertEqual(self.tables.bucket_count, 780)
        premium = hand_classes(self.tables, "Premium")
        self.assertEqual(sum(hand.combos for hand in premium), 14_868)

    def test_deal_keeps_hero_cards_and_never_repeats(self) -> None:
        state = np.asarray([12345], dtype=np.uint64)
        hero = np.asarray([48, 49, 44, 45], dtype=np.int64)
        hands = np.empty((6, 4), dtype=np.int64)
        board = np.empty(5, dtype=np.int64)
        for _ in range(500):
            _deal(state, 2, hero, hands, board)
            self.assertEqual(list(hands[2]), list(hero))
            cards = list(hands.ravel()) + list(board)
            self.assertEqual(len(set(cards)), 29)
            self.assertTrue(all(0 <= card < 52 for card in cards))

    def test_best_response_against_folding_table_is_exact(self) -> None:
        policy = _passive_policy(self.tree, self.tables.bucket_count)
        hand = next(h for h in hand_classes(self.tables, "Premium") if h.text == "KcKdAcAd")
        rows = run_tasks(
            [hand], [0, 4], policy=policy, tables=self.tables, tree=self.tree,
            rank5=self.rank5, comb=self.comb, fit_samples=200, test_samples=200, seed=1,
        )
        utg, sb = rows
        # Everyone folds to a pot open: the opener collects the blinds exactly.
        self.assertAlmostEqual(utg["ev_best_response"]["pot_open"], 1.5)
        self.assertAlmostEqual(utg["se_best_response"]["pot_open"], 0.0, places=9)
        self.assertAlmostEqual(utg["ev_best_response"]["fold"], 0.0)
        self.assertAlmostEqual(sb["ev_best_response"]["pot_open"], 1.0)
        self.assertAlmostEqual(sb["ev_best_response"]["fold"], -0.5)
        self.assertEqual(utg["verdict"], "must_not_fold")

    def test_training_updates_are_finite(self) -> None:
        shape = (self.tree.decision_count, self.tables.bucket_count, 3)
        regrets, strategy = np.zeros(shape), np.zeros(shape)
        states = np.asarray([1, 2], dtype=np.uint64)
        train_batch(
            300, states, 1.0, self.tables.bucket_of, self.rank5, self.comb,
            self.tree.actor, self.tree.decision_index, self.tree.children,
            self.tree.action_count, self.tree.behind, self.tree.sidepot_count,
            self.tree.sidepot_amount, self.tree.sidepot_eligible_mask, regrets, strategy,
        )
        self.assertTrue(np.isfinite(regrets).all())
        self.assertGreater(np.abs(regrets[0]).sum(), 0.0)
        self.assertGreater(strategy.sum(), 0.0)
        self.assertTrue((strategy >= 0).all())

    def test_ratio_and_verdict(self) -> None:
        estimate = _ratio(10.0, 10.0, 10.0, 10.0, 10.0)
        self.assertEqual(estimate.mean, 1.0)
        self.assertEqual(estimate.se, 0.0)
        labels = ["fold", "limp", "pot_open"]
        self.assertEqual(
            verdict(labels, [Estimate(0, 0), Estimate(-1, 0.1), Estimate(-2, 0.1)], [-0.5, -1.0, -1.5]),
            "fold_is_best_response",
        )
        self.assertEqual(
            verdict(labels, [Estimate(0, 0), Estimate(-0.1, 0.1), Estimate(-2, 0.1)], [0.1, -1.0, -1.5]),
            "inconclusive",
        )

    def test_colex_index_is_a_bijection(self) -> None:
        self.assertEqual(colex_index((0, 1, 2, 3)), 0)
        self.assertEqual(colex_index((48, 49, 50, 51)), 270_724)


if __name__ == "__main__":
    unittest.main()
