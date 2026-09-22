"""Checks for the glossary-derived speech-recognition bias prompt."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import lexicon  # noqa: E402


class TableParsingTests(unittest.TestCase):
    def test_header_row_is_not_a_term(self):
        self.assertNotIn("Term", lexicon.english_terms())
        self.assertNotIn("English", lexicon.english_terms())

    def test_real_glossary_terms_are_present(self):
        terms = lexicon.english_terms()
        for expected in ("Bankroll", "Check-raise", "Effective stack", "Implied odds"):
            self.assertIn(expected, terms)

    def test_separator_rows_are_skipped(self):
        rows = lexicon._table_rows("| Term | Thai |\n|---|---|\n| Flop | ฟลอป |\n")
        self.assertEqual(rows, [["Flop", "ฟลอป"]])

    def test_text_outside_tables_is_ignored(self):
        self.assertEqual(lexicon._table_rows("# Heading\n\nsome prose\n"), [])


class BiasPromptTests(unittest.TestCase):
    def test_prompt_stays_within_the_whisper_limit(self):
        self.assertLessEqual(len(lexicon.bias_prompt()), lexicon.MAX_PROMPT_CHARS + len(lexicon.PROMPT_SUFFIX))

    def test_prompt_is_anchored_in_thai_on_both_ends(self):
        prompt = lexicon.bias_prompt()
        self.assertTrue(prompt.startswith(lexicon.PROMPT_PREFIX))
        self.assertTrue(prompt.endswith(lexicon.PROMPT_SUFFIX))

    def test_prompt_carries_poker_vocabulary(self):
        self.assertIn("Bankroll", lexicon.bias_prompt())


if __name__ == "__main__":
    unittest.main()
