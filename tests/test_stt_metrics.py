"""Checks for the Thai/English speech-recognition scoring helpers."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import metrics  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_punctuation_and_case_are_folded(self):
        self.assertEqual(metrics.normalize("C-Bet, บน Flop!"), "c bet บน flop")

    def test_thai_characters_survive_normalisation(self):
        self.assertEqual(metrics.normalize("เช็กเรส"), "เช็กเรส")


class CharacterErrorRateTests(unittest.TestCase):
    def test_identical_text_scores_zero(self):
        self.assertEqual(metrics.character_error_rate("เจอ c-bet บน flop", "เจอ c-bet บน flop"), 0.0)

    def test_spacing_differences_are_ignored(self):
        self.assertEqual(metrics.character_error_rate("เจอ c-bet", "เจอc-bet"), 0.0)

    def test_empty_reference_with_output_is_total_error(self):
        self.assertEqual(metrics.character_error_rate("", "อะไรสักอย่าง"), 1.0)

    def test_empty_reference_and_output_is_no_error(self):
        self.assertEqual(metrics.character_error_rate("", ""), 0.0)

    def test_substitution_is_bounded_by_reference_length(self):
        rate = metrics.character_error_rate("ฟลอป", "ฟลอบ")
        self.assertAlmostEqual(rate, 0.25)


class EnglishTermTests(unittest.TestCase):
    def test_hyphenated_jargon_stays_one_token(self):
        self.assertEqual(metrics.english_terms("เจอ c-bet บน flop"), ("c-bet", "flop"))

    def test_recall_counts_only_expected_terms(self):
        self.assertEqual(metrics.english_recall("เจอ c-bet บน flop", "เจอ ซีเบท บน flop"), 0.5)

    def test_reference_without_english_is_perfect_recall(self):
        self.assertEqual(metrics.english_recall("เช็กเรสบนบอร์ดแห้ง", "เช็กเรส"), 1.0)

    def test_extra_english_does_not_raise_recall(self):
        self.assertEqual(metrics.english_recall("flop", "flop turn river"), 1.0)


if __name__ == "__main__":
    unittest.main()
