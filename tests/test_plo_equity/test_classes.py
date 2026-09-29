import unittest

from plo_equity.cards import canonical_hand, enumerate_classes, parse_hand


class SuitClassTest(unittest.TestCase):
    def test_complete_physical_space_collapses_to_expected_classes(self):
        classes = enumerate_classes()
        self.assertEqual(len(classes), 16_432)
        self.assertEqual(sum(hand.multiplicity for hand in classes), 270_725)

    def test_order_and_global_suit_relabeling_are_invariant(self):
        first = parse_hand("As Ah Ks Kh")
        second = parse_hand("Kd Ac Kc Ad")
        self.assertEqual(canonical_hand(first), canonical_hand(second))
        self.assertEqual(parse_hand("asahkskh"), first)
        self.assertEqual(parse_hand("ASAHKSKH"), first)

    def test_invalid_physical_hand_is_rejected(self):
        for text in ("AsAsKsKh", "AsKsQh", "AAKK"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_hand(text)
