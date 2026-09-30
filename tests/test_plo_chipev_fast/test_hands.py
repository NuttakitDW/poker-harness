from __future__ import annotations

import itertools
import unittest

from plo_chipev.abstraction import hand_observation
from plo_chipev_fast.hands import HandLookup, combinadic_index
from plo_icm.cards import DECK


class HandLookupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lookup = HandLookup.build()

    def test_all_physical_hands_have_lexicographic_combinadic_entries(self) -> None:
        self.assertEqual(self.lookup.physical_count, 270_725)
        self.assertEqual(self.lookup.bucket_count, 572)
        seen = set()
        for lex_index, cards in enumerate(itertools.combinations(range(52), 4)):
            self.assertEqual(combinadic_index(cards), lex_index)
            bucket = int(self.lookup.combo_to_bucket[lex_index])
            self.assertGreaterEqual(bucket, 0)
            self.assertLess(bucket, self.lookup.bucket_count)
            seen.add(bucket)
        self.assertEqual(len(seen), self.lookup.bucket_count)

    def test_lookup_matches_existing_feature_abstraction(self) -> None:
        for cards in ((0, 1, 2, 3), (0, 17, 34, 51), (12, 13, 14, 15), (7, 20, 31, 45)):
            names = tuple(DECK[index] for index in cards)
            expected = hand_observation(names, "features")
            self.assertEqual(self.lookup.bucket_names[self.lookup.bucket_for_cards(cards)], expected)
