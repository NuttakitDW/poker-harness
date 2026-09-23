"""Checks for judging the low half of a PLO Hi/Lo hand."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import plo_hand  # noqa: E402
import plo_low  # noqa: E402


class HiLoWordTests(unittest.TestCase):
    def test_spoken_forms_of_hi_lo(self):
        for text in ("แล้วถ้าเล่นในไฮโร", "ไฮโล Ace of Better", "PLO8", "hi/lo", "eight or better"):
            with self.subTest(text=text):
                self.assertTrue(plo_low.is_hilo(text))

    def test_plain_plo_is_not_hi_lo(self):
        self.assertFalse(plo_low.is_hilo("PLO สี่ใบ A299 ประเภทไหน"))


class LowStudyTests(unittest.TestCase):
    def test_ace_deuce_is_the_nut_low_draw(self):
        study = plo_low.study("A992")
        self.assertEqual(study.low_cards, "A-2")
        self.assertTrue(study.nut_low_cards)
        self.assertGreater(study.nut_low_rate, 0)
        self.assertGreater(study.nut_low_draw_rate, 0)

    def test_hand_without_two_low_cards_has_no_low(self):
        study = plo_low.study("KKQJ")
        self.assertEqual(study.low_cards, "")
        self.assertEqual(study.nut_low_rate, 0)

    def test_third_low_card_protects_against_counterfeit(self):
        self.assertGreater(plo_low.study("A32K").nut_low_rate, plo_low.study("A2KQ").nut_low_rate)

    def test_ace_three_is_not_the_nut_low(self):
        self.assertFalse(plo_low.study("A3KK").nut_low_cards)


class HiLoBlockTests(unittest.TestCase):
    def test_hi_lo_block_says_ace_deuce_is_the_best_low(self):
        block = plo_hand.context_block("ไฮโล", earlier="A 2 9 9 โพดำ 2 ใบคือ A กับ 2", hilo=True)
        self.assertIn("A-2", block)
        self.assertIn("nut low", block)
        self.assertIn("PLO Hi/Lo", block)
        # ระดับจากแบบฝึก PLO high ใช้กับ Hi/Lo ตรง ๆ ไม่ได้
        self.assertNotIn("ระดับที่ถูก", block)


class FollowUpTests(unittest.TestCase):
    def conversation(self, *questions):
        import brain
        history = brain.Conversation()
        for question in questions:
            history = history.with_turn("user", question).with_turn("assistant", "ตอบแล้วค่ะ")
        return brain, history

    def test_hi_lo_follow_up_borrows_the_last_hand(self):
        brain, history = self.conversation("มี 4 ใบ A, 2, 9, 9 โพดํา 2 ใบคือ A กับ 2")
        block = brain.plo_context("แล้วถ้าเล่นในไฮโร แฮนด์นี้ยังดีอยู่ไหม", history)
        self.assertIn("PLO Hi/Lo", block)
        self.assertIn("A-9-9-2", block)

    def test_second_hi_lo_follow_up_still_finds_the_hand(self):
        brain, history = self.conversation("มี 4 ใบ A, 2, 9, 9 โพดํา 2 ใบคือ A กับ 2",
                                           "แล้วถ้าเล่นในไฮโร แฮนด์นี้ยังดีอยู่ไหม")
        block = brain.plo_context("หมายถึงไฮโล Ace of Better ไม่ใช่ไฮโลเลอร์", history)
        self.assertIn("nut low", block)

    def test_the_hand_from_a_moment_ago_is_borrowed(self):
        brain, history = self.conversation("K J 10 9 ซิงเกิลซุต")
        self.assertIn("K-J-T-9", brain.plo_context("แฮนด์ตะกี้ไง", history))

    def test_thanks_does_not_drag_the_old_hand_along(self):
        brain, history = self.conversation("มี 4 ใบ A, 2, 9, 9")
        self.assertEqual(brain.plo_context("ขอบคุณค่ะ", history), "")


if __name__ == "__main__":
    unittest.main()
