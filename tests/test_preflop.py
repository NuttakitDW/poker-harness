"""Checks reading the GTO preflop charts that back short-stack answers."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import preflop  # noqa: E402

RANKS = preflop.RANKS


def hand_order() -> list[str]:
    """ชื่อมือ 169 แบบเรียงตามช่องในตาราง เหมือนที่ตัวสร้างเขียนลงไฟล์"""
    names = []
    for row, high in enumerate(RANKS):
        for col, low in enumerate(RANKS):
            names.append(high * 2 if row == col
                         else f"{high}{low}s" if row < col else f"{low}{high}o")
    return names


def chart(hero="UTG", villain=None, scenario="RFI", stack=80, raises=(), calls=(), page=4):
    """ชาร์ตปลอมหนึ่งใบ ให้ระบุแค่มือที่ raise กับ call ที่เหลือคือ fold"""
    codes = "".join("R" if hand in raises else "C" if hand in calls else "F"
                    for hand in hand_order())
    return {"stack": stack, "section": "TEST", "page": page, "hero": hero,
            "villain": villain, "scenario": scenario, "actions": codes, "mixed": {}}


def book(charts, game="tournament"):
    return {"game": game, "title": "คู่มือทดสอบ", "file": "test.pdf",
            "hand_order": hand_order(), "charts": charts}


class ParsingTests(unittest.TestCase):
    def test_a_stack_in_big_blinds_is_read(self):
        self.assertEqual(preflop.parse("เหลือ 12BB ที่ CO เปิดได้ไหม").stack, 12)

    def test_a_stack_written_in_thai_is_read(self):
        self.assertEqual(preflop.parse("เหลือ 25 บีบี อยู่ BTN").stack, 25)

    def test_the_stack_unit_is_not_mistaken_for_the_big_blind_seat(self):
        self.assertEqual(preflop.parse("80BB ที่ UTG เปิดอะไรได้").hero, "UTG")

    def test_the_big_blind_seat_is_still_read_when_it_is_a_seat(self):
        request = preflop.parse("อยู่ BB เจอ UTG เปิดมา 100BB")
        self.assertEqual(request.hero, "BB")
        self.assertEqual(request.villain, "UTG")

    def test_thai_position_words_are_understood(self):
        self.assertEqual(preflop.parse("อยู่ปุ่ม เปิดเป็นคนแรก").hero, "BTN")

    def test_the_kind_of_game_comes_from_the_words_used(self):
        self.assertEqual(preflop.parse("ทัวร์นาเมนต์ 20BB BTN เปิด").game, "tournament")
        self.assertEqual(preflop.parse("cash game 100BB CO เปิด").game, "cash")

    def test_a_three_bet_question_is_recognised(self):
        self.assertEqual(preflop.parse("โดน 3-bet จาก BTN ตอนอยู่ CO").scenario, "3-Bet")

    def test_asking_about_shoving_counts_as_opening(self):
        self.assertEqual(preflop.parse("3BB ที่ UTG shove ได้มือไหน").scenario, "RFI")

    def test_a_question_without_a_seat_is_not_usable(self):
        self.assertFalse(preflop.parse("ICM คืออะไร").usable)


class NotationTests(unittest.TestCase):
    def test_pairs_running_to_the_top_become_a_plus(self):
        made = book([chart(raises=("AA", "KK", "QQ", "JJ", "TT"))])
        self.assertEqual(preflop.notation(made, made["charts"][0], "raise"), "TT+")

    def test_pairs_in_the_middle_become_a_range(self):
        made = book([chart(raises=("99", "88", "77"))])
        self.assertEqual(preflop.notation(made, made["charts"][0], "raise"), "99-77")

    def test_suited_hands_with_the_top_kicker_become_a_plus(self):
        made = book([chart(raises=("AKs", "AQs", "AJs"))])
        self.assertEqual(preflop.notation(made, made["charts"][0], "raise"), "AJs+")

    def test_suited_hands_lower_down_stay_a_range(self):
        made = book([chart(raises=("K9s", "K8s", "K7s"))])
        self.assertEqual(preflop.notation(made, made["charts"][0], "raise"), "K9s-K7s")

    def test_offsuit_hands_are_marked_with_o(self):
        made = book([chart(raises=("AKo", "AQo"))])
        self.assertEqual(preflop.notation(made, made["charts"][0], "raise"), "AQo+")

    def test_pairs_come_before_suited_and_offsuit(self):
        made = book([chart(raises=("AA", "AKs", "AKo"))])
        self.assertEqual(preflop.notation(made, made["charts"][0], "raise"), "AA, AKs, AKo")


class FindingTests(unittest.TestCase):
    def setUp(self):
        charts = [chart(stack=80, hero="UTG", raises=("AA",)),
                  chart(stack=20, hero="UTG", raises=("AA", "KK")),
                  chart(stack=20, hero="BTN", raises=("AA", "KK", "QQ")),
                  chart(stack=20, hero="CO", villain="UTG", scenario="3-Bet",
                        raises=("AA",), calls=("KK",))]
        self.original = preflop.books
        preflop.books = lambda: (book(charts),)
        self.addCleanup(lambda: setattr(preflop, "books", self.original))

    def test_the_nearest_stack_is_chosen(self):
        _, found, _ = preflop.find("เหลือ 18BB ที่ UTG เปิดอะไรได้")
        self.assertEqual(found["stack"], 20)

    def test_the_seat_must_match(self):
        _, found, _ = preflop.find("25BB อยู่ BTN เปิดเป็นคนแรก")
        self.assertEqual(found["hero"], "BTN")

    def test_the_situation_must_match(self):
        _, found, _ = preflop.find("20BB อยู่ CO โดน 3-bet จาก UTG")
        self.assertEqual(found["scenario"], "3-Bet")
        self.assertEqual(found["villain"], "UTG")

    def test_a_seat_with_no_chart_finds_nothing(self):
        self.assertIsNone(preflop.find("20BB อยู่ SB เปิดเป็นคนแรก"))

    def test_a_vague_question_finds_nothing(self):
        self.assertIsNone(preflop.find("ICM ทำงานยังไง"))

    def test_the_context_block_carries_the_range_and_the_source(self):
        block = preflop.context_block("20BB อยู่ CO โดน 3-bet จาก UTG")
        self.assertIn("raise: AA", block)
        self.assertIn("call: KK", block)
        self.assertIn("คู่มือทดสอบ", block)
        self.assertIn("fold", block)

    def test_hands_outside_the_opening_range_are_not_listed_one_by_one(self):
        charts = [chart(stack=20, hero="CO", villain="UTG", scenario="3-Bet",
                        raises=("AA",), calls=("KK",))]
        made = book(charts)
        made["charts"][0]["actions"] = made["charts"][0]["actions"].replace("F", "-")
        original = preflop.books
        preflop.books = lambda: (made,)
        self.addCleanup(lambda: setattr(preflop, "books", original))
        block = preflop.context_block("20BB อยู่ CO โดน 3-bet จาก UTG")
        self.assertIn("ไม่ได้อยู่ในเรนจ์", block)
        self.assertNotIn("32o", block)

    def test_a_stack_that_is_not_in_the_book_is_flagged(self):
        block = preflop.context_block("เหลือ 3BB ที่ UTG จะ shove")
        self.assertIn("3 BB", block)
        self.assertIn("20 BB", block)
        self.assertIn("กว้างขึ้น", block)

    def test_an_exact_stack_needs_no_note(self):
        self.assertNotIn("หมายเหตุ", preflop.context_block("20BB ที่ UTG เปิดเป็นคนแรก"))

    def test_nothing_matched_gives_an_empty_block(self):
        self.assertEqual(preflop.context_block("ICM ทำงานยังไง"), "")


if __name__ == "__main__":
    unittest.main()
