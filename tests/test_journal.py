"""Checks the event stream shown while talking and stored for later reading."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import engines  # noqa: E402
import journal  # noqa: E402


class DescribeTests(unittest.TestCase):
    def test_an_utterance_line_carries_length_level_and_lag(self):
        line = journal.describe("utterance", {"seconds": 2.7, "peak": 0.312,
                                              "silence_before": 0.9, "lag": 0.12,
                                              "cut_short": False})
        self.assertIn("2.70s", line)
        self.assertIn("0.312", line)
        self.assertIn("0.12s", line)
        self.assertNotIn("เพดาน", line)

    def test_a_turn_cut_at_the_limit_says_so(self):
        line = journal.describe("utterance", {"seconds": 45.0, "cut_short": True})
        self.assertIn("เพดาน", line)

    def test_an_answer_line_breaks_the_timing_into_stages(self):
        line = journal.describe("answer", {"sentences": 3, "opened": 0.35, "first_token": 1.2,
                                           "first_audio": 1.62, "synth_first": 0.42,
                                           "total": 5.8, "cards": ["TH/13-tournaments"]})
        for part in ("0.35s", "1.20s", "1.62s", "5.80s", "TH/13-tournaments"):
            self.assertIn(part, line)

    def test_a_missing_number_shows_a_dash_instead_of_crashing(self):
        self.assertIn("-", journal.describe("answer", {"sentences": 0, "cards": []}))

    def test_an_unknown_event_still_prints_its_fields(self):
        line = journal.describe("something-new", {"count": 2})
        self.assertIn("something-new", line)
        self.assertIn("count=2", line)


class WritingTests(unittest.TestCase):
    def test_every_event_lands_in_the_file_as_one_json_line(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "deep" / "log.jsonl"
            log = journal.Journal(path, echo=False)
            log.note("utterance", seconds=1.0)
            log.note("heard", text="สวัสดี")
            log.close()
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["kind"] for record in lines], ["utterance", "heard"])
        self.assertEqual(lines[1]["text"], "สวัสดี")
        self.assertIn("since", lines[0])

    def test_a_value_that_cannot_be_json_is_written_as_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "log.jsonl"
            log = journal.Journal(path, echo=False)
            log.note("odd", value=object())
            log.close()
            record = json.loads(path.read_text(encoding="utf-8").strip())
        self.assertIsInstance(record["value"], str)

    def test_events_without_a_file_only_show_on_screen(self):
        log = journal.Journal(None, echo=False)
        log.note("utterance", seconds=1.0)
        log.close()

    def test_noting_before_starting_does_nothing(self):
        journal.stop()
        journal.note("utterance", seconds=1.0)


class UsableTextTests(unittest.TestCase):
    def test_thai_speech_is_kept(self):
        self.assertTrue(engines.usable_text("ลูกชุบได้ยินไหม"))

    def test_english_poker_terms_are_kept(self):
        self.assertTrue(engines.usable_text("all in"))

    def test_a_wrong_language_guess_is_thrown_away(self):
        self.assertFalse(engines.usable_text("pid синcidos"))

    def test_nothing_heard_is_not_usable(self):
        self.assertFalse(engines.usable_text("   "))

    def test_other_languages_are_left_alone(self):
        self.assertTrue(engines.usable_text("pid синcidos", language="EN"))


if __name__ == "__main__":
    unittest.main()


class RepetitionTests(unittest.TestCase):
    """ผลถอดเสียงที่วนคำเดิมซ้ำ ๆ คืออาการค้างของตัวถอดเสียง"""

    def test_a_looping_transcript_is_rejected(self):
        looped = "ล่าคมยัง" + "ความรวมกัน" * 20
        self.assertTrue(engines.repetitive(looped))
        self.assertFalse(engines.usable_text(looped))

    def test_a_normal_question_is_not_seen_as_looping(self):
        normal = "เปิด 63 offsuit จาก UTG ตอนเหลือสามโต๊ะควรทำอย่างไรดี"
        self.assertFalse(engines.repetitive(normal))
        self.assertTrue(engines.usable_text(normal))

    def test_a_short_answer_is_never_seen_as_looping(self):
        self.assertFalse(engines.repetitive("ครับผม"))
