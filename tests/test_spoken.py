"""Checks for turning model answers into speech-ready Thai text."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
from spoken import to_speech  # noqa: E402


class MarkdownStrippingTests(unittest.TestCase):
    def test_bold_and_bullets_become_plain_speech(self):
        self.assertEqual(to_speech("**สรุป** range แคบลง\n\n- ข้อหนึ่ง\n- ข้อสอง"),
                         "สรุป range แคบลง ข้อหนึ่ง ข้อสอง")

    def test_links_keep_the_label_and_drop_the_target(self):
        self.assertEqual(to_speech("ดูที่ [การ์ด](topics/13.md)"), "ดูที่ การ์ด")

    def test_bare_urls_are_removed(self):
        self.assertEqual(to_speech("อ่าน https://example.com/a ต่อ"), "อ่าน ต่อ")

    def test_headings_lose_their_hashes(self):
        self.assertEqual(to_speech("## หัวข้อ"), "หัวข้อ")


class NumberWordTests(unittest.TestCase):
    """เครื่องอ่านออกเสียงอ่านเลขอารบิกเพี้ยน จึงเขียนทุกจำนวนเป็นคำไทยก่อน"""

    def test_a_stack_in_big_blinds_is_read_in_thai(self):
        self.assertEqual(to_speech("ที่ UTG 100 BB เปิดได้"), "ที่ UTG หนึ่งร้อย BB เปิดได้")

    def test_a_stack_written_together_is_read_in_thai(self):
        self.assertEqual(to_speech("สแตก 25bb"), "stack ยี่สิบห้า bb")

    def test_a_spelled_out_big_blind_is_read_in_thai(self):
        self.assertEqual(to_speech("เหลือ 11 big blind"), "เหลือ สิบเอ็ด big blind")

    def test_a_decimal_open_size_is_read_in_thai(self):
        self.assertEqual(to_speech("เปิด 2.5 BB"), "เปิด สองจุดห้า BB")

    def test_a_range_of_sizes_reads_both_ends_in_thai(self):
        self.assertEqual(to_speech("เปิด 2.5 ถึง 3 BB"), "เปิด สองจุดห้า ถึง สาม BB")

    def test_money_with_commas_is_read_in_thai(self):
        self.assertEqual(to_speech("ได้เงินมา 1,100 จ่ายเองแค่ 900"),
                         "ได้เงินมา หนึ่งพันหนึ่งร้อย จ่ายเองแค่ เก้าร้อย")

    def test_a_percent_glued_to_thai_is_read_in_thai(self):
        self.assertEqual(to_speech("ขายหุ้น50%"), "ขายหุ้น ห้าสิบ เปอร์เซ็นต์")

    def test_a_markup_decimal_is_read_in_thai(self):
        self.assertEqual(to_speech("markup 1.1"), "markup หนึ่งจุดหนึ่ง")

    def test_thousands_written_with_k_are_read_in_thai(self):
        self.assertEqual(to_speech("ทัวร์ 1.5k"), "ทัวร์ หนึ่งพันห้าร้อย")

    def test_a_pocket_pair_in_digits_is_read_as_two_cards(self):
        self.assertEqual(to_speech("ถือ 33 อยู่ UTG"), "ถือ สาม สาม อยู่ UTG")

    def test_a_repeated_digit_with_a_unit_is_still_a_number(self):
        self.assertEqual(to_speech("33 เปอร์เซ็นต์"), "สามสิบสาม เปอร์เซ็นต์")

    def test_bet_levels_are_said_in_english(self):
        self.assertEqual(to_speech("โดน 3-bet แล้ว 4bet"), "โดน three-bet แล้ว four-bet")

    def test_digits_inside_names_are_left_alone(self):
        self.assertEqual(to_speech("PLO8 กับ v2"), "PLO8 กับ v2")


class SymbolTests(unittest.TestCase):
    def test_percent_is_spoken(self):
        self.assertEqual(to_speech("25%"), "ยี่สิบห้า เปอร์เซ็นต์")

    def test_currency_moves_after_the_amount(self):
        # paxa อ่าน "ดอลลาร์" เพี้ยนเป็น "ดอลลาห์" แต่อ่านคำอังกฤษถูก
        self.assertEqual(to_speech("$150"), "หนึ่งร้อยห้าสิบ dollar")

    def test_thai_spelled_dollar_is_spoken_in_english(self):
        self.assertEqual(to_speech("ราว 665 ดอลลาร์ ก็พอ"), "ราว หกร้อยหกสิบห้า dollar ก็พอ")

    def test_digit_range_uses_thai_word(self):
        self.assertEqual(to_speech("3-5 ครั้ง"), "สาม ถึง ห้า ครั้ง")

    def test_unicode_minus_is_spoken_as_minus(self):
        self.assertEqual(to_speech("กำไร −30"), "กำไร ลบ สามสิบ")


class PlayingCardTests(unittest.TestCase):
    def test_suits_become_thai_names(self):
        self.assertEqual(to_speech("A♣7♦2♠"), "เอซ ดอกจิก เจ็ด ข้าวหลามตัด สอง โพดำ")

    def test_hearts_and_ten_are_named(self):
        self.assertEqual(to_speech("T♥"), "สิบ โพแดง")

    def test_flop_is_read_card_by_card_not_as_a_range(self):
        self.assertEqual(to_speech("flop 6-5-4 ได้ nut straight"), "flop หก ห้า สี่ ได้ nut straight")
        self.assertEqual(to_speech("T-9-8"), "สิบ เก้า แปด")

    def test_two_cards_with_a_letter_are_cards(self):
        self.assertEqual(to_speech("A-K ใหญ่สุด"), "เอซ เค ใหญ่สุด")

    def test_two_falling_digits_are_cards(self):
        self.assertEqual(to_speech("มี 7-6 ด้วย"), "มี เจ็ด หก ด้วย")

    def test_hand_with_a_letter_is_read_card_by_card(self):
        self.assertEqual(to_speech("มือ JJ63 เป็น Marginal"), "มือ แจ็ค แจ็ค หก สาม เป็น Marginal")
        self.assertEqual(to_speech("KKQJ"), "เค เค คิว แจ็ค")

    def test_offsuit_and_suited_shorthand_are_spoken_in_full(self):
        # "A9o" เคยถูกอ่านว่า "เอ เก้า โอ"
        self.assertEqual(to_speech("A9o เป็นมือ fold"), "เอซ เก้า offsuit เป็นมือ fold")
        self.assertEqual(to_speech("KQs"), "เค คิว suited")
        self.assertEqual(to_speech("เปิดด้วย AJs+ กับ ATo+"),
                         "เปิดด้วย เอซ แจ็ค suited ขึ้นไป กับ เอซ สิบ offsuit ขึ้นไป")

    def test_shorthand_next_to_thai_or_in_a_range_is_spoken_in_full(self):
        self.assertEqual(to_speech("มือA9oเป็นมือ fold"), "มือ เอซ เก้า offsuit เป็นมือ fold")
        self.assertEqual(to_speech("ATo-A8o"), "เอซ สิบ offsuit ถึง เอซ แปด offsuit")

    def test_pair_with_plus_is_read_as_that_pair_and_up(self):
        self.assertEqual(to_speech("shove TT+ กับ 22+"), "shove สิบ สิบ ขึ้นไป กับ สอง สอง ขึ้นไป")

    def test_plain_numbers_stay_numbers(self):
        self.assertEqual(to_speech("ติด nuts หกสิบห้า ครั้ง"), "ติด nuts หกสิบห้า ครั้ง")

    def test_two_numbers_are_still_a_range(self):
        self.assertEqual(to_speech("3-5 ครั้ง"), "สาม ถึง ห้า ครั้ง")
        self.assertEqual(to_speech("blinds 10-20"), "blinds สิบ ถึง ยี่สิบ")

    def test_letters_without_a_suit_are_left_alone(self):
        self.assertEqual(to_speech("range ของ A high"), "range ของ A high")


class LoanwordTests(unittest.TestCase):
    """Paxa mispronounces poker jargon spelled in Thai letters, so it goes out in English."""

    def test_the_name_of_the_game_goes_out_in_english(self):
        self.assertEqual(to_speech("เล่นโป๊กเกอร์มานาน"), "เล่น Poker มานาน")

    def test_tournament_is_spelled_in_english(self):
        self.assertEqual(to_speech("ลงทัวร์นาเมนต์วันอาทิตย์"), "ลง tournament วันอาทิตย์")

    def test_street_names_are_spelled_in_english(self):
        self.assertEqual(to_speech("ฟลอปมาแล้วเทิร์นกับริเวอร์"), "flop มาแล้ว turn กับ river")

    def test_a_spelling_variant_is_converted_too(self):
        self.assertEqual(to_speech("โปกเกอร์ออนไลน์"), "Poker ออนไลน์")

    def test_stakes_spelled_in_thai_go_out_in_english(self):
        self.assertEqual(to_speech("ลดสเตกลง"), "ลด stakes ลง")

    def test_english_already_in_the_answer_is_left_alone(self):
        self.assertEqual(to_speech("c-bet บน flop แห้ง"), "c-bet บน flop แห้ง")

    def test_converted_words_do_not_run_into_the_thai_around_them(self):
        self.assertEqual(to_speech("เรนจ์แคบ"), "range แคบ")

    def test_a_longer_word_wins_over_a_shorter_one_inside_it(self):
        self.assertEqual(to_speech("แบดบีทติดกัน"), "bad beat ติดกัน")

    def test_pot_is_spelled_in_english(self):
        self.assertEqual(to_speech("พอตเท่าไหร่"), "pot เท่าไหร่")

    def test_table_actions_are_spelled_in_english(self):
        self.assertEqual(to_speech("จะคอลหรือเรสดี ถ้าไม่ไหวก็โฟลด์"),
                         "จะ call หรือ raise ดี ถ้าไม่ไหวก็ fold")

    def test_check_raise_still_wins_over_the_bare_check(self):
        self.assertEqual(to_speech("เช็คเรสได้เลย"), "check-raise ได้เลย")

    def test_positions_are_spelled_in_english(self):
        self.assertEqual(to_speech("เปิดจากคัตออฟแล้วโดนทรีเบต"),
                         "เปิดจาก cutoff แล้วโดน three-bet")
