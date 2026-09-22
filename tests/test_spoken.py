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


class SymbolTests(unittest.TestCase):
    def test_percent_is_spoken(self):
        self.assertEqual(to_speech("25%"), "25 เปอร์เซ็นต์")

    def test_currency_moves_after_the_amount(self):
        self.assertEqual(to_speech("$150"), "150 ดอลลาร์")

    def test_digit_range_uses_thai_word(self):
        self.assertEqual(to_speech("3-5 ครั้ง"), "3 ถึง 5 ครั้ง")

    def test_unicode_minus_is_spoken_as_minus(self):
        self.assertEqual(to_speech("กำไร −30"), "กำไร ลบ 30")


class PlayingCardTests(unittest.TestCase):
    def test_suits_become_thai_names(self):
        self.assertEqual(to_speech("A♣7♦2♠"), "เอซ ดอกจิก 7 ข้าวหลามตัด 2 โพดำ")

    def test_hearts_and_ten_are_named(self):
        self.assertEqual(to_speech("T♥"), "สิบ โพแดง")

    def test_letters_without_a_suit_are_left_alone(self):
        self.assertEqual(to_speech("range ของ A high"), "range ของ A high")


class LoanwordTests(unittest.TestCase):
    """Paxa mispronounces poker jargon spelled in Thai letters, so it goes out in English."""

    def test_the_name_of_the_game_goes_out_in_english(self):
        self.assertEqual(to_speech("เล่นโป๊กเกอร์มานาน"), "เล่น poker มานาน")

    def test_tournament_is_spelled_in_english(self):
        self.assertEqual(to_speech("ลงทัวร์นาเมนต์วันอาทิตย์"), "ลง tournament วันอาทิตย์")

    def test_street_names_are_spelled_in_english(self):
        self.assertEqual(to_speech("ฟลอปมาแล้วเทิร์นกับริเวอร์"), "flop มาแล้ว turn กับ river")

    def test_a_spelling_variant_is_converted_too(self):
        self.assertEqual(to_speech("โปกเกอร์ออนไลน์"), "poker ออนไลน์")

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
