from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from o8_fl.buckets import Abstraction
from o8_fl.cards import card_ids
from o8_fl.evaluator import NO_LOW
from o8_fl.trainer import Trainer, combo_index_native, layout, terminal_value
from o8_fl.buckets import combo_index
from o8_fl.tree import PublicTree


class TrainerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.abstraction = Abstraction.build(samples=50_000)
        cls.tree = PublicTree.build()

    def test_layout_is_contiguous_and_sized_by_street(self) -> None:
        offsets, size = layout(self.tree, self.abstraction.bucket_counts)
        counts = self.abstraction.bucket_counts
        decisions = np.flatnonzero(self.tree.kind == 0)
        expected = sum(counts[self.tree.street[n]] * 3 for n in decisions)
        self.assertEqual(size, expected)
        starts = sorted(int(offsets[n]) for n in decisions)
        self.assertEqual(starts[0], 0)
        self.assertEqual(len(set(starts)), len(starts))

    def test_native_combo_index(self) -> None:
        for cards in ((0, 1, 2, 3), (5, 17, 33, 51), (48, 49, 50, 51)):
            self.assertEqual(combo_index_native(np.array(cards)), combo_index(cards))

    def test_terminal_values(self) -> None:
        t = self.tree
        fold = t.history_to_node["rf"]  # big blind folds to a raise
        self.assertEqual(terminal_value(t.kind, t.committed, t.folder, fold, 0, 0, 0, NO_LOW, NO_LOW), 1.0)
        self.assertEqual(terminal_value(t.kind, t.committed, t.folder, fold, 1, 0, 0, NO_LOW, NO_LOW), -1.0)
        show = t.history_to_node["ck" + "kk" * 3]
        self.assertEqual(terminal_value(t.kind, t.committed, t.folder, show, 0, 10, 5, NO_LOW, NO_LOW), 1.0)
        self.assertEqual(terminal_value(t.kind, t.committed, t.folder, show, 1, 10, 5, NO_LOW, NO_LOW), -1.0)

    def test_training_is_deterministic_on_one_thread_and_policies_are_distributions(self) -> None:
        a = Trainer(self.tree, self.abstraction)
        b = Trainer(self.tree, self.abstraction)
        a.run(3000, threads=1, seed=4)
        b.run(3000, threads=1, seed=4)
        np.testing.assert_array_equal(a.regret, b.regret)
        self.assertGreaterEqual(float(a.regret.min()), 0.0)  # CFR+ keeps regrets non-negative
        policy = a.average_policy(0, self.abstraction.preflop_class(card_ids("AsAh3s2h")))
        self.assertAlmostEqual(float(policy.sum()), 1.0)
        self.assertEqual(policy.size, 3)

    def test_each_thread_alternates_the_traverser(self) -> None:
        from o8_fl.trainer import traverser_for
        for threads in (1, 2, 14):
            for thread in range(min(threads, 3)):
                seats = {traverser_for(0, i, thread, threads) for i in range(4)}
                self.assertEqual(seats, {0, 1})

    def test_pool_training_uses_equity_buckets_and_is_deterministic(self) -> None:
        from o8_fl.pool import DealPool
        rng = np.random.default_rng(0)
        n = 300
        cards = np.array([rng.permutation(52)[:13] for _ in range(n)], dtype=np.uint8)
        buckets = rng.integers(0, [7, 9, 11], size=(n, 2, 3)).astype(np.uint16)
        centroids = tuple(np.zeros((k, 3), dtype=np.float32) for k in (7, 9, 11))
        deal_pool = DealPool(cards, buckets, centroids)
        a = Trainer(self.tree, self.abstraction, deal_pool)
        b = Trainer(self.tree, self.abstraction, deal_pool)
        offsets, size = layout(self.tree, (self.abstraction.bucket_counts[0], 7, 9, 11))
        self.assertEqual(a.regret.size, size)
        a.run(2000, threads=1, seed=5)
        b.run(2000, threads=1, seed=5)
        np.testing.assert_array_equal(a.strategy_sum, b.strategy_sum)
        river = self.tree.history_to_node["ck" + "kk" * 2]  # first river decision
        self.assertGreater(sum(a.visits(river, k) for k in range(11)), 0)
        with self.assertRaises(ValueError):
            a.average_policy(river, 11)

    def test_checkpoint_round_trip(self) -> None:
        a = Trainer(self.tree, self.abstraction)
        a.run(500, threads=1, seed=1)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ckpt.npz"
            a.save(path)
            b = Trainer.load(path, self.tree, self.abstraction)
        np.testing.assert_array_equal(a.strategy_sum, b.strategy_sum)
        self.assertEqual(a.iterations, b.iterations)


if __name__ == "__main__":
    unittest.main()
