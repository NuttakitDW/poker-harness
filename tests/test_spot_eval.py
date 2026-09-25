"""The spot-reading test set: scoring rules, and a guard that passing questions keep passing."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import preflop  # noqa: E402
import spot_eval  # noqa: E402


class ReadTests(unittest.TestCase):
    def test_a_single_opponent_counts_as_the_shover(self):
        read = spot_eval.regex_reader("BB เจอ SB ออลอิน 8bb ถือ K7o")
        self.assertEqual(read["shovers"], ["SB"])
        self.assertEqual(read["hands"], ["K7o"])

    def test_every_field_is_present(self):
        read = spot_eval.regex_reader("hello")
        self.assertEqual(set(read), set(spot_eval.FIELDS))


class ScoreTests(unittest.TestCase):
    def test_only_the_labelled_fields_are_checked(self):
        marks = spot_eval.check({"hero": "SB", "stack": 5}, {**spot_eval.empty(), "hero": "SB",
                                                            "stack": 5.0, "players": 9})
        self.assertEqual(marks, {"hero": True, "stack": True})

    def test_shovers_and_hands_ignore_order(self):
        marks = spot_eval.check({"shovers": ["UTG", "BTN"], "hands": ["KQo", "KQs"]},
                                {**spot_eval.empty(), "shovers": ["BTN", "UTG"],
                                 "hands": ["KQs", "KQo"]})
        self.assertTrue(all(marks.values()))

    def test_a_wrong_field_fails_the_question(self):
        marks = spot_eval.check({"hero": "SB", "stack": 5}, {**spot_eval.empty(), "hero": "BB",
                                                            "stack": 5})
        self.assertEqual(marks, {"hero": False, "stack": True})

    def test_the_report_gives_overall_and_per_field_accuracy(self):
        cases = [{"question": "a", "expected": {"hero": "SB"}},
                 {"question": "b", "expected": {"hero": "BB", "stack": 5}}]
        result = spot_eval.evaluate(cases, lambda q: {**spot_eval.empty(), "hero": "SB", "stack": 5})
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.fields["hero"], (1, 2))
        self.assertEqual(result.fields["stack"], (1, 1))
        self.assertIn("1/2", result.render())


class CorpusTests(unittest.TestCase):
    """Every labelled question must keep passing; a fixed known gap must lose its label."""

    @classmethod
    def setUpClass(cls):
        cls.cases = spot_eval.load()
        cls.result = spot_eval.evaluate(cls.cases, spot_eval.regex_reader)

    def test_the_corpus_is_labelled_with_known_fields_only(self):
        self.assertGreaterEqual(len(self.cases), 25)
        for case in self.cases:
            with self.subTest(question=case["question"]):
                self.assertTrue(set(case["expected"]) <= set(spot_eval.FIELDS))

    def test_questions_that_passed_before_still_pass(self):
        for row in self.result.rows:
            if not row.case.get("known_gap"):
                with self.subTest(question=row.case["question"]):
                    self.assertTrue(row.passed, row.failed_fields)

    def test_a_known_gap_that_now_passes_must_drop_its_label(self):
        for row in self.result.rows:
            if row.case.get("known_gap"):
                with self.subTest(question=row.case["question"]):
                    self.assertFalse(row.passed, "fixed: remove known_gap from questions.jsonl")


if __name__ == "__main__":
    unittest.main()
