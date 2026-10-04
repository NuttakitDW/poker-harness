from __future__ import annotations

import itertools
import random
import unittest

import numpy as np

from o8_fl.buckets import (HANDS, PREFLOP_CLASSES, UNSEEN, Abstraction, build_preflop, class_name,
                           combo_index, dense_map)
from o8_fl.cards import card_ids


class PreflopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lookup, cls.names, cls.weights = build_preflop()

    def test_combo_index_matches_itertools(self) -> None:
        for index, combo in enumerate(itertools.islice(itertools.combinations(range(52), 4), 0, 5000, 7)):
            self.assertEqual(combo_index(combo), index * 7)
        self.assertEqual(combo_index((48, 49, 50, 51)), HANDS - 1)

    def test_every_hand_has_a_class_and_weights_sum(self) -> None:
        self.assertEqual(len(self.names), PREFLOP_CLASSES)
        self.assertEqual(int(self.weights.sum()), HANDS)
        self.assertEqual(int(self.lookup.max()), PREFLOP_CLASSES - 1)

    def test_suit_relabelling_keeps_the_class(self) -> None:
        rng = random.Random(2)
        for _ in range(500):
            cards = tuple(sorted(rng.sample(range(52), 4)))
            perm = rng.sample(range(4), 4)
            moved = tuple(sorted((c >> 2) * 4 + perm[c & 3] for c in cards))
            self.assertEqual(self.lookup[combo_index(cards)], self.lookup[combo_index(moved)])

    def test_double_suited_and_rainbow_differ(self) -> None:
        ds = self.lookup[combo_index(tuple(sorted(card_ids("AsKs2h3h"))))]
        rb = self.lookup[combo_index(tuple(sorted(card_ids("AsKd2h3c"))))]
        self.assertNotEqual(ds, rb)
        self.assertEqual(self.weights[ds], 12)  # 4 x 3 suit choices
        self.assertEqual(self.weights[rb], 24)

    def test_class_name(self) -> None:
        self.assertEqual(class_name(card_ids("2h3hAsKs")), "AsKs3h2h")


class DenseMapTest(unittest.TestCase):
    def test_unseen_keys_share_bucket_zero(self) -> None:
        mapping = dense_map(np.array([0, 3, 0, 1]))
        self.assertEqual(mapping.tolist(), [UNSEEN, 1, UNSEEN, 2])

    def test_small_build_and_round_trip(self) -> None:
        import tempfile
        from pathlib import Path
        a = Abstraction.build(samples=20_000)
        self.assertEqual(a.bucket_counts[0], PREFLOP_CLASSES)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "abs.npz"
            a.save(path)
            b = Abstraction.load(path)
        np.testing.assert_array_equal(a.flop_map, b.flop_map)
        self.assertEqual(a.preflop_names, b.preflop_names)
        self.assertEqual(a.preflop_class(card_ids("AsKs2h3h")), b.preflop_class(card_ids("2h3hAsKs")))


if __name__ == "__main__":
    unittest.main()
