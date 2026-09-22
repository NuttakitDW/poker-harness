"""Checks for Thai spoken-number normalisation used in speech scoring."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
from thai_numbers import normalize_numbers  # noqa: E402


class SpokenNumberTests(unittest.TestCase):
    def test_single_digit(self):
        self.assertEqual(normalize_numbers("หกคน"), "6คน")

    def test_tens_with_yi_prefix(self):
        self.assertEqual(normalize_numbers("ยี่สิบห้า"), "25")

    def test_eleven_uses_et(self):
        self.assertEqual(normalize_numbers("สิบเอ็ด"), "11")

    def test_hundreds(self):
        self.assertEqual(normalize_numbers("หนึ่งร้อยยี่สิบ"), "120")

    def test_millions_multiply_the_running_total(self):
        self.assertEqual(normalize_numbers("ห้าล้าน"), "5000000")

    def test_decimal_point(self):
        self.assertEqual(normalize_numbers("สองจุดห้า"), "2.5")

    def test_percent_word_becomes_symbol(self):
        self.assertEqual(normalize_numbers("ยี่สิบห้าเปอร์เซ็นต์"), "25%")

    def test_digits_already_written_are_untouched(self):
        self.assertEqual(normalize_numbers("25%"), "25%")

    def test_surrounding_thai_words_are_preserved(self):
        self.assertEqual(
            normalize_numbers("เปิด raise สองจุดห้า big blind"),
            "เปิด raise 2.5 big blind",
        )

    def test_thai_words_that_merely_look_numeric_are_left_alone(self):
        self.assertEqual(normalize_numbers("flop แห้ง"), "flop แห้ง")


class ScoringIntegrationTests(unittest.TestCase):
    def test_spoken_and_written_numbers_score_as_equal(self):
        import metrics

        self.assertEqual(
            metrics.character_error_rate(
                "bankroll ควรมีกี่ buy-in สำหรับ micro stakes หกคน",
                "Bankroll ควรมีกี่ Buy-in สำหรับ Micro Stakes 6 คน",
            ),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
