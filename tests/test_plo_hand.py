"""Checks for reading a spoken PLO hand and judging it with the miracle-flop test."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import plo_hand  # noqa: E402
import retrieval  # noqa: E402


class SpokenHandTests(unittest.TestCase):
    def test_thai_rank_words_become_a_hand(self):
        self.assertEqual(retrieval.hands("แจ็ค แจ็ค 6 3"), ("JJ63",))
        self.assertEqual(retrieval.hands("คิง คิง ควีน แจ็ค"), ("KKQJ",))

    def test_english_rank_words_become_a_hand(self):
        # "A Jack Ten Ten" เคยอ่านไม่ออก โมเดลจึงเดาระดับเองโดยไม่มีข้อเท็จจริงจากโค้ด
        question = "เพียโล A Jack Ten Ten Single Suited A Jack โพดํา อันนี้ประเภทแฮนด์อะไรครับ"
        self.assertEqual(retrieval.hands(question), ("AJTT",))
        self.assertEqual(retrieval.hands("Ace King Queen Jack"), ("AKQJ",))
        self.assertEqual(retrieval.hands("two pair four bet"), ())

    def test_capitalised_suited_marks_a_suited_ace(self):
        self.assertTrue(plo_hand.suited_ace("A Jack Ten Ten Single Suited A Jack โพดํา"))

    def test_repeat_mark_doubles_the_card(self):
        self.assertEqual(retrieval.hands("อยากรู้ว่าคิงๆ ควีน แจ็ค ดับเบิลซูต"), ("KKQJ",))

    def test_hand_is_sorted_high_to_low(self):
        self.assertEqual(retrieval.hands("6 แจ็ค 3 แจ็ค"), ("JJ63",))

    def test_written_hand_followed_by_its_suits_is_still_a_hand(self):
        # "A299 A โพดำ 2 โพดำ" เคยต่อกันเป็นห้าใบจนไม่เป็นมือ
        self.assertEqual(retrieval.hands("เพียโร 4 ใบ A299 A โพดํา 2 พอดํา อันนี้ประเภทไหน"), ("A992",))

    def test_suits_named_card_by_card_give_the_shape(self):
        self.assertEqual(plo_hand.shape("A299 A โพดํา 2 พอดํา"), "single-suited")
        self.assertEqual(plo_hand.shape("มีดอกจิก 2 ใบ แจ็คอีกใบเป็นไดมอนด์ 3 เป็นโพดำ"), "single-suited")
        self.assertEqual(plo_hand.shape("A โพดำ K โพดำ Q โพแดง J โพแดง"), "double-suited")

    def test_suited_ace_is_detected_from_the_named_suits(self):
        self.assertTrue(plo_hand.suited_ace("มี 4 ใบ A, 2, 9, 9 โพดํา 2 ใบคือ A กับ 2 ครับ"))
        self.assertTrue(plo_hand.suited_ace("A299 A โพดํา 2 พอดํา"))
        self.assertFalse(plo_hand.suited_ace("แจ็ค-แจ็ค 6-3 มีดอกจิก 2 ใบ ก็คือแจ็คกับ 6 ส่วน A เป็นไดมอนด์"))
        self.assertFalse(plo_hand.suited_ace("A 2 9 9"))

    def test_five_or_more_cards_are_not_a_hand(self):
        self.assertEqual(retrieval.hands("คิง ควีน แจ็ค คิง คิง 2 ใบ"), ())

    def test_ordinary_thai_words_are_not_cards(self):
        self.assertEqual(retrieval.hands("เอาแบบนี้เองเหรอ สิบบาท"), ())

    def test_shape_words(self):
        self.assertEqual(plo_hand.shape("ดับเบิลซูต"), "double-suited")
        self.assertEqual(plo_hand.shape("ซิงเกิ้ลสูท"), "single-suited")
        self.assertEqual(plo_hand.shape("rainbow"), "rainbow")
        self.assertEqual(plo_hand.shape("rb"), "rainbow")
        self.assertEqual(plo_hand.shape("RB"), "rainbow")
        self.assertIsNone(plo_hand.shape("herbal remedy"))
        self.assertIsNone(plo_hand.shape("แจ็ค แจ็ค 6 3"))


class DrillTests(unittest.TestCase):
    def test_drill_tier_is_found_without_suits(self):
        found = plo_hand.drill("JJ63")
        self.assertEqual(found.tier, "Marginal")
        self.assertEqual(found.shape, "single-suited")

    def test_drill_hand_written_out_of_order_on_the_site_is_found(self):
        # เว็บวาง A-2-9-9 แต่มือที่ค้นเรียงใหญ่ไปเล็กเป็น A992
        block = plo_hand.context_block("แฮนด์ต่อไปครับ A 2 9 9 ซูต มี A 2 เป็นซูต โพดำ")
        self.assertIn("Speculative", block)
        self.assertIn("single-suited", block)

    def test_unknown_hand_has_no_drill(self):
        self.assertIsNone(plo_hand.drill("5432"))


class MiracleFlopTests(unittest.TestCase):
    def test_rundown_flops_nut_straights(self):
        study = plo_hand.study("KKQJ")
        self.assertGreater(study.rates["straight"], 0)
        self.assertEqual(study.examples["straight"], "T-9-8")

    def test_one_way_pair_only_flops_nuts_through_the_set(self):
        study = plo_hand.study("JJ63")
        # 6-3 ทำ nut straight ได้แค่ flop อย่าง 5-4-2 ส่วนใหญ่ต้องพึ่ง set ของ J
        self.assertLess(study.rates["straight"] * 10, study.rates["set"])
        self.assertEqual(study.working["J-J"], max(study.working.values()))

    def test_dominated_low_rundown_rarely_flops_nuts(self):
        self.assertLess(plo_hand.study("9753").nut_rate, plo_hand.study("JT98").nut_rate)

    def test_rundown_wraps_while_one_way_pair_does_not(self):
        rundown, pair = plo_hand.study("JT98"), plo_hand.study("JJ63")
        self.assertGreater(rundown.wrap_rate, 0)
        self.assertEqual(pair.wrap_rate, 0)
        self.assertGreater(rundown.nut_rate + rundown.draw_rate, 2 * (pair.nut_rate + pair.draw_rate))

    def test_rates_are_shares_of_all_flops(self):
        study = plo_hand.study("AAKK")
        self.assertTrue(0 < study.nut_rate < 1)
        self.assertAlmostEqual(study.nut_rate, sum(study.rates.values()), places=9)


class ContextTests(unittest.TestCase):
    def test_block_carries_drill_tier_and_miracle_flop(self):
        block = plo_hand.context_block("แจ็ค แจ็ค 6 3")
        self.assertIn("Marginal", block)
        self.assertIn("miracle flop", block)
        self.assertIn("ไม่ขึ้นกับตำแหน่ง", block)

    def test_follow_up_shape_uses_hand_from_before(self):
        block = plo_hand.context_block("ดับเบิลซูต", earlier="คิง คิง ควีน แจ็ค")
        self.assertIn("K-K-Q-J", block)
        self.assertIn("double-suited", block)

    def test_current_hand_wins_over_earlier_hand(self):
        block = plo_hand.context_block("แจ็ค แจ็ค 6 3", earlier="คิง คิง ควีน แจ็ค")
        self.assertIn("J-J-6-3", block)
        self.assertNotIn("K-K-Q-J", block)

    def test_card_pairs_are_dashed_so_they_are_not_read_as_numbers(self):
        block = plo_hand.context_block("8 7 6 5")
        self.assertIn("6-5", block)
        self.assertIn("มือ 8-7-6-5", block)
        self.assertNotRegex(block, r"(?<![\w-])[2-9]{2}(?= \d+%)")

    def test_split_hand_outside_drill_is_trash_like_its_drill_twin(self):
        # K-J-7-6 ไม่มีในแบบฝึก โมเดลเคยลอกระดับ Marginal ของ K-J-T-9 จากตาก่อนมาตอบ
        block = plo_hand.context_block("คิงแจ็ค 7-6 ดับเบิลซูเต็ด")
        self.assertIn("ระดับที่ควรเป็น: Trash", block)
        self.assertIn("Q-J-7-6", block)

    def test_connected_hand_is_not_called_split(self):
        self.assertNotIn("Hold'em สองมือ", plo_hand.context_block("คิง แจ็ค 10 9"))

    def test_split_hand_with_ace_or_pair_is_not_forced_to_trash(self):
        self.assertNotIn("ระดับที่ควรเป็น", plo_hand.context_block("A K 7 6"))
        self.assertNotIn("ระดับที่ควรเป็น", plo_hand.context_block("K K 7 6"))

    def test_hand_outside_drill_warns_against_earlier_tier(self):
        block = plo_hand.context_block("คิงแจ็ค 7-6", earlier="คิงแจ็ค 10 9")
        self.assertIn("ห้ามลอกระดับ", block)

    def test_preflop_drill_answer_is_in_block(self):
        # AA87 ไม่มีในแบบฝึกจัดระดับ โมเดลเคยเดาว่า Speculative แล้วบอกให้ limp จาก UTG
        # ทั้งที่แบบฝึก preflop ตอบว่า raise ได้จากทุกตำแหน่ง
        block = plo_hand.context_block("แฮนด์นี้ AA8700 ตําแหน่งที่ UTG คนแรก")
        self.assertIn("UTG", block)
        self.assertIn("→ Raise", block)

    def test_preflop_drills_of_other_hands_stay_out(self):
        self.assertNotIn("→ Raise", plo_hand.context_block("คิง คิง ควีน แจ็ค"))

    def test_block_says_hand_is_only_four_cards(self):
        # ถอดเสียงได้ AA8700 โมเดลเคยพูดถึงไพ่ 0 ที่ไม่มีอยู่จริง
        block = plo_hand.context_block("แฮนด์นี้ AA8700")
        self.assertIn("มีแค่สี่ใบนี้", block)

    def test_no_hand_no_block(self):
        self.assertEqual(plo_hand.context_block("สวัสดีค่ะ"), "")


if __name__ == "__main__":
    unittest.main()
