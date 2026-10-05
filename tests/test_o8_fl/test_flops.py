from __future__ import annotations

import collections
import unittest

import numpy as np

from o8_fl.buckets import HANDS, Abstraction
from o8_fl.cards import card_ids, card_text
from o8_fl.flops import (NO_BUCKET, canonical_flops, class_order, flop_buckets, representatives,
                         select_flops, texture)


class FlopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.abstraction = Abstraction.build(samples=20_000)

    def test_there_are_1755_canonical_flops_covering_every_flop(self) -> None:
        flops = canonical_flops()
        self.assertEqual(len(flops), 1755)
        self.assertEqual(sum(w for _, w in flops), 22100)

    def test_texture(self) -> None:
        self.assertEqual(texture(card_ids("As7d2c")), ("rainbow", "unpaired", 3, "A"))  # the ace counts as low
        self.assertEqual(texture(card_ids("KsKd2s")), ("two-tone", "paired", 1, "K-Q"))
        self.assertEqual(texture(card_ids("9h8h7h")), ("monotone", "unpaired", 2, "J-9"))

    def test_selection_is_deterministic_distinct_and_covers_every_texture(self) -> None:
        a, b = select_flops(120, seed=1), select_flops(120, seed=1)
        self.assertEqual(a, b)
        self.assertEqual(len(set(a)), 120)
        textures = {texture(f) for f, _ in canonical_flops()}
        self.assertEqual({texture(f) for f in a}, textures)

    def test_class_order_groups_every_combo_by_class(self) -> None:
        order = class_order(self.abstraction)
        self.assertEqual(sorted(order.tolist()), list(range(HANDS)))
        classes = self.abstraction.preflop[order]
        self.assertTrue(np.all(np.diff(classes) >= 0))

    def test_flop_buckets_skip_board_cards_and_match_the_class_layout(self) -> None:
        flop = card_ids("As7d2c")
        centroids = np.array([[0.2, 0.0, 0.3], [0.5, 0.1, 0.4], [0.8, 0.2, 0.3]], dtype=np.float32)
        order = class_order(self.abstraction)[:600]
        cdf = np.cumsum(np.ones(HANDS))
        buckets = flop_buckets(np.array(flop), centroids, order, cdf, seed=3, runouts=4, opponents=2, strong=2)
        self.assertEqual(buckets.shape, (600,))
        combos = list(__import__("itertools").combinations(range(52), 4))
        for i, index in enumerate(order):
            conflict = bool(set(combos[index]) & set(flop))
            self.assertEqual(buckets[i] == NO_BUCKET, conflict)
        self.assertTrue(np.all((buckets < 3) | (buckets == NO_BUCKET)))

    def test_representatives_avoid_the_board(self) -> None:
        flop = card_ids("AsKd2c")
        reps = representatives(self.abstraction, flop)
        for cls, text in reps.items():
            cards = card_ids(text)
            self.assertFalse(set(cards) & set(flop))
            self.assertEqual(self.abstraction.preflop_class(cards), cls)
        self.assertIn(self.abstraction.preflop_class(card_ids("AsAh3h2s")), reps)


if __name__ == "__main__":
    unittest.main()
