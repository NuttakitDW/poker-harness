"""M1: the 169 hand classes, their combos and the blocker matrix W."""

import itertools
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import hands  # noqa: E402


class CombosTest(unittest.TestCase):
    def test_169_classes_cover_all_1326_combos(self):
        self.assertEqual(len(hands.CLASSES), 169)
        self.assertEqual(int(hands.COUNTS.sum()), 1326)
        self.assertEqual(len(hands.COMBOS), 1326)

    def test_pair_suited_offsuit_counts(self):
        self.assertEqual(hands.COUNTS[hands.index("AA")], 6)
        self.assertEqual(hands.COUNTS[hands.index("AKs")], 4)
        self.assertEqual(hands.COUNTS[hands.index("AKo")], 12)
        self.assertEqual(hands.COUNTS[hands.index("72o")], 12)

    def test_every_combo_lands_in_its_class(self):
        for (a, b), cls in zip(hands.COMBOS, hands.CLASS_OF):
            label = hands.CLASSES[cls]
            high, low = sorted((a // 4, b // 4), reverse=True)
            self.assertEqual(label[:2], hands.RANKS[high] + hands.RANKS[low])
            if high != low:
                self.assertEqual(label[2], "s" if a % 4 == b % 4 else "o")

    def test_grid_layout(self):
        self.assertEqual(hands.CLASSES[0], "AA")
        self.assertEqual(hands.CLASSES[1], "AKs")
        self.assertEqual(hands.CLASSES[13], "AKo")
        self.assertEqual(hands.CLASSES[168], "22")

    def test_unknown_label_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "hand class"):
            hands.index("AKx")


class BlockerTest(unittest.TestCase):
    def test_aa_vs_aks_is_12_not_24(self):
        self.assertEqual(hands.W[hands.index("AA"), hands.index("AKs")], 12)

    def test_aa_vs_aa_is_6(self):
        self.assertEqual(hands.W[hands.index("AA"), hands.index("AA")], 6)

    def test_symmetric(self):
        np.testing.assert_array_equal(hands.W, hands.W.T)

    def test_rows_sum_to_combos_times_1225(self):
        np.testing.assert_array_equal(hands.W.sum(axis=1), hands.COUNTS * 1225)

    def test_matches_brute_force_on_a_few_pairs(self):
        for first, second in [("KK", "AKo"), ("AKs", "AKo"), ("T9s", "98s"), ("72o", "AA")]:
            i, j = hands.index(first), hands.index(second)
            mine = [c for c, k in zip(hands.COMBOS, hands.CLASS_OF) if k == i]
            theirs = [c for c, k in zip(hands.COMBOS, hands.CLASS_OF) if k == j]
            brute = sum(1 for x, y in itertools.product(mine, theirs) if not set(x) & set(y))
            self.assertEqual(hands.W[i, j], brute, (first, second))

    def test_conditional_matrix_rows_are_distributions(self):
        np.testing.assert_allclose(hands.M.sum(axis=1), 1.0)


if __name__ == "__main__":
    unittest.main()
