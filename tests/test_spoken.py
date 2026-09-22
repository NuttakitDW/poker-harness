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
