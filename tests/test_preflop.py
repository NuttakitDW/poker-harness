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

    def test_a_misheard_big_blind_is_still_read_as_the_stack(self):
        for said in ("20 บิ๊กบาย", "20 บิกบาย", "20 บิ๊กบลาย", "20 บิ๊กบลายด์", "20 big blinds"):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(f"ขอชาร์ต {said} จาก Button").stack, 20)

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

    def test_asking_for_a_chart_at_a_seat_means_opening_first(self):
        request = preflop.parse("พี่ขอพรีฟลอปชาร์ต 50 Big blind ตําแหน่ง Button หน่อย")
        self.assertEqual((request.hero, request.stack, request.scenario), ("BTN", 50, "RFI"))
        self.assertTrue(request.usable)

    def test_asking_for_a_range_at_a_seat_means_opening_first(self):
        self.assertEqual(preflop.parse("เรนจ์ CO 30BB").scenario, "RFI")

    def test_raise_first_in_with_a_hyphen_is_recognised(self):
        self.assertEqual(preflop.parse("ขอ Raise first-in จาก Button 20 Big blind").scenario,
                         "RFI")

    def test_a_misheard_chart_word_still_means_opening_when_preflop_is_said(self):
        request = preflop.parse("พี่ขอพรีฟลอปฉาด จากตําแหน่ง Button 20 Big blind")
        self.assertEqual(request.scenario, "RFI")

    def test_a_misheard_cutoff_is_still_the_cutoff(self):
        self.assertEqual(preflop.parse("จากบัตรทอดเนี่ยครับ เปิดแฮนด์ไหนได้").hero, "CO")

    def test_a_seat_alone_is_still_not_enough(self):
        self.assertFalse(preflop.parse("อยู่ BTN รู้สึกยังไง").usable)

    def test_holding_a_hand_at_a_seat_means_opening_first(self):
        request = preflop.parse("ถือ 33 อยู่ UTG 100 Big blind เล่นยังไงดี")
        self.assertEqual((request.hero, request.stack, request.scenario), ("UTG", 100, "RFI"))

    def test_a_question_without_a_seat_is_not_usable(self):
        self.assertFalse(preflop.parse("ICM คืออะไร").usable)

    def test_blind_seats_spoken_as_two_words_are_read(self):
        self.assertEqual(preflop.parse("อยู่ Big blind เจอ CO เปิด").hero, "BB")
        self.assertEqual(preflop.parse("อยู่ small blind เจอ CO เปิด").hero, "SB")


class SeatRoleTests(unittest.TestCase):
    """คนพูดชื่อคนเปิดก่อน แล้วค่อยพูดตำแหน่งตัวเอง ลำดับคำจึงบอกบทบาทไม่ได้"""

    def test_the_seat_that_three_bets_an_opener_is_the_hero(self):
        # ถามจริงในวงคุย เคยได้ชาร์ต BTN เจอ SB 3-bet แทนที่จะเป็น BB เจอ BTN เปิด
        request = preflop.parse(
            "ขอฉาก 3-bet หน่อย ถ้าเกิด Button เปิดมา จาก เอ่อ ถ้า Button raise first in "
            "มาตอน 20 Big blind ตําแหน่ง Big blind 3-bet อะไรได้บ้าง?")
        self.assertEqual((request.hero, request.villain, request.scenario, request.stack),
                         ("BB", "BTN", "RFI", 20))

    def test_the_seat_answering_an_open_is_the_hero(self):
        request = preflop.parse(
            "ไม่ใช่ ไม่ใช่ ขอว่า Button น่ะจะ Action ยังไงบ้าง ไม่ใช่ว่า Button น่ะเจออะไรบ้าง "
            "เออ แล้วขอ Big blind ไม่ได้ขอ small blind Button เปิด แล้ว Big blind ทําอะไรได้บ้าง?")
        self.assertEqual((request.hero, request.villain, request.scenario),
                         ("BB", "BTN", "RFI"))

    def test_an_opener_hit_by_a_named_three_bettor_is_the_hero(self):
        request = preflop.parse("BTN เปิดแล้วโดน BB 3-bet ทำไงดี")
        self.assertEqual((request.hero, request.villain, request.scenario),
                         ("BTN", "BB", "3-Bet"))

    def test_an_opener_facing_a_three_bet_from_a_seat_is_the_hero(self):
        request = preflop.parse("CO เปิด แล้วโดน 3-bet จาก BTN")
        self.assertEqual((request.hero, request.villain, request.scenario),
                         ("CO", "BTN", "3-Bet"))


class CarryTests(unittest.TestCase):
    def test_a_follow_up_keeps_the_stack_and_game_said_earlier(self):
        text = preflop.carry("BB เจอ BTN เปิด ไม่มีได้ยังไง",
                             ["ทัวร์นาเมนต์ 20BB BTN เปิด", "อะไรนะ"])
        request = preflop.parse(text)
        self.assertEqual((request.stack, request.game), (20, "tournament"))

    def test_the_latest_stack_said_wins(self):
        text = preflop.carry("BB เจอ BTN เปิด", ["50BB CO เปิด", "20BB BTN เปิด"])
        self.assertEqual(preflop.parse(text).stack, 20)

    def test_a_stack_in_the_question_is_not_replaced(self):
        text = preflop.carry("30BB BB เจอ BTN เปิด", ["20BB BTN เปิด"])
        self.assertEqual(preflop.parse(text).stack, 30)


    def test_a_seat_answering_a_request_for_a_range_gets_the_chart(self):
        text = preflop.carry("ตําแหน่ง UTG 100 Big blind",
                             ["ให้ตาราง Range ไม่ได้นี่", "ได้ ได้"])
        self.assertTrue(preflop.parse(text).usable)

    def test_a_range_asked_long_ago_is_not_carried(self):
        text = preflop.carry("อยู่ BTN รู้สึกยังไง", ["ขอ range หน่อย", "อะไรนะ", "เหนื่อย", "โอเค"])
        self.assertFalse(preflop.parse(text).usable)


class HandTests(unittest.TestCase):
    def test_a_hand_with_letters_is_read(self):
        self.assertEqual(preflop.hands_in("เปิด A8o ได้ไหม"), ["A8o"])

    def test_the_high_card_comes_first(self):
        self.assertEqual(preflop.hands_in("8A offsuit"), ["A8o"])

    def test_suited_is_read(self):
        self.assertEqual(preflop.hands_in("KQ suited"), ["KQs"])

    def test_a_pair_has_no_suffix(self):
        self.assertEqual(preflop.hands_in("ถือ JJ อยู่"), ["JJ"])

    def test_ten_spoken_in_thai_comes_out_as_a_teen_number(self):
        # "สิบแปดออฟสูท" ตัวถอดเสียงเขียนเป็น 18 offsuit
        self.assertEqual(preflop.hands_in("เปิด 18 offsuit จาก button"), ["T8o"])

    def test_ten_written_as_digits_is_read(self):
        self.assertEqual(preflop.hands_in("10 9 suited"), ["T9s"])

    def test_digits_without_a_suit_word_are_not_a_hand(self):
        self.assertEqual(preflop.hands_in("เหลือ 18 คน 98 เปอร์เซ็นต์"), [])

    def test_no_suit_word_means_both_shapes(self):
        self.assertEqual(preflop.hands_in("AK ล่ะ"), ["AKs", "AKo"])

    def test_the_stack_is_not_a_hand(self):
        self.assertEqual(preflop.hands_in("20 big blind เปิด 18 offsuit"), ["T8o"])

    def test_lower_case_english_words_are_not_hands(self):
        self.assertEqual(preflop.hands_in("look at this"), [])

    def test_the_answer_for_an_asked_hand_is_read_from_the_chart(self):
        made = book([chart(raises=("A9o",))])
        lines = preflop.hand_answers(made, made["charts"][0], ["T8o", "A9o"])
        self.assertEqual(lines, ["T8o = fold 100%", "A9o = raise 100%"])

    def test_a_mixed_hand_answer_carries_the_frequencies(self):
        made_chart = chart(raises=("77",))
        made_chart["mixed"] = {"77": {"raise": 0.5, "fold": 0.5}}
        lines = preflop.hand_answers(book([made_chart]), made_chart, ["77"])
        self.assertEqual(lines, ["77 = raise 50% / fold 50%"])


class ShareTests(unittest.TestCase):
    def test_a_pair_is_six_combos(self):
        made = book([chart(raises=("AA",))])
        self.assertAlmostEqual(preflop.range_share(made, made["charts"][0], "raise"), 6 / 1326)

    def test_suited_and_offsuit_hands_count_their_combos(self):
        made = book([chart(raises=("AKs", "AKo"))])
        self.assertAlmostEqual(preflop.range_share(made, made["charts"][0], "raise"), 16 / 1326)

    def test_a_mixed_hand_counts_by_its_frequency(self):
        made_chart = chart(raises=("AA",))
        made_chart["mixed"] = {"AA": {"raise": 0.5, "fold": 0.5}}
        self.assertAlmostEqual(preflop.range_share(book([made_chart]), made_chart, "raise"),
                               3 / 1326)


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
        self.assertRegex(block, r"raise \(ราว [0-9.]+% ของมือทั้งหมด\): AA")
        self.assertRegex(block, r"call \(ราว [0-9.]+% ของมือทั้งหมด\): KK")
        self.assertIn("คู่มือทดสอบ", block)
        self.assertIn("fold", block)

    def test_the_block_says_what_a_raise_against_a_three_bet_is(self):
        block = preflop.context_block("20BB อยู่ CO โดน 3-bet จาก UTG")
        self.assertIn("ช่อง raise ในตารางนี้คือเรนจ์ 4-bet ของ CO ใส่ UTG", block)

    def test_an_opening_chart_has_no_reraise_line(self):
        self.assertNotIn("ช่อง raise", preflop.context_block("20BB UTG เปิดอะไรได้"))

    def test_the_context_block_answers_the_asked_hand_directly(self):
        block = preflop.context_block("20BB อยู่ CO โดน 3-bet จาก UTG ถือ KK กับ 18 offsuit")
        self.assertIn("KK = call", block)
        self.assertIn("T8o = fold", block)

    def test_an_asked_hand_is_named_even_without_a_chart(self):
        block = preflop.context_block("มี 18 offsuit เนี่ยเปิดได้ไหม")
        self.assertIn("T8o", block)
        self.assertNotIn("raise:", block)

    def test_a_chart_on_screen_tells_the_model_not_to_read_hands_aloud(self):
        block = preflop.context_block("20BB อยู่ CO โดน 3-bet จาก UTG", on_screen=True)
        self.assertIn("บนจอ", block)

    def test_a_chart_not_on_screen_says_nothing_about_the_screen(self):
        self.assertNotIn("บนจอ", preflop.context_block("20BB อยู่ CO โดน 3-bet จาก UTG"))

    def test_the_block_says_how_wide_the_range_is(self):
        block = preflop.context_block("20BB อยู่ CO โดน 3-bet จาก UTG")
        self.assertIn("ราว 0.5% ของมือทั้งหมด", block)

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
