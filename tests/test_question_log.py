"""Checks the Discord question log used to find sentences the parser cannot read."""

import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import preflop  # noqa: E402
import question_log  # noqa: E402

WHEN = datetime.datetime(2026, 9, 25, 13, 5, 0)


class RecordTests(unittest.TestCase):
    def test_a_question_is_one_json_line_in_that_days_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = question_log.record(
                question_log.entry(question="BTN shove 10bb", source="text", kind="chart",
                                   request=preflop.Request(hero="BTN", stack=10), server="S",
                                   channel="general", author="nut"),
                when=WHEN, folder=Path(folder))
            question_log.record(question_log.entry(question="ping?", source="text", kind="not_found"),
                                when=WHEN, folder=Path(folder))
            lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(path.name, "discord-20260925.jsonl")
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["question"], "BTN shove 10bb")
        self.assertEqual(first["parsed"]["hero"], "BTN")
        self.assertEqual(first["at"], "2026-09-25T13:05:00")

    def test_thai_is_kept_readable_in_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = question_log.record(question_log.entry(question="สมอลไบล์", source="voice",
                                                          kind="not_found"),
                                       when=WHEN, folder=Path(folder))
            self.assertIn("สมอลไบล์", path.read_text(encoding="utf-8"))

    def test_a_voice_question_keeps_what_was_heard(self):
        made = question_log.entry(question="SB เจอ UTG", source="voice", kind="chart",
                                  audio="voice-message.ogg")
        self.assertEqual((made["source"], made["audio"]), ("voice", "voice-message.ogg"))


class ReviewTests(unittest.TestCase):
    def test_only_questions_without_a_chart_are_listed(self):
        with tempfile.TemporaryDirectory() as folder:
            for question, kind in (("BTN shove 10bb", "chart"), ("บัตท่อนแจม", "not_found"),
                                   ("BTN open 30bb", "push_fold_only"), ("x", "error")):
                question_log.record(question_log.entry(question=question, source="text", kind=kind),
                                    when=WHEN, folder=Path(folder))
            misses = question_log.misses(Path(folder))
        self.assertEqual([m["question"] for m in misses], ["บัตท่อนแจม", "BTN open 30bb", "x"])

    def test_the_review_groups_misses_by_kind(self):
        text = question_log.review([
            {"at": "2026-09-25T13:05:00", "question": "บัตท่อนแจม", "kind": "not_found",
             "source": "voice", "parsed": {"hero": None, "stack": None}},
        ])
        self.assertIn("not_found (1)", text)
        self.assertIn("บัตท่อนแจม", text)
        self.assertIn("voice", text)


class RetentionTests(unittest.TestCase):
    def test_files_older_than_the_retention_are_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "discord-20260601.jsonl"
            kept = Path(folder) / "discord-20260701.jsonl"
            other = Path(folder) / "voice-20200101.jsonl"
            for path in (old, kept, other):
                path.write_text("{}\n", encoding="utf-8")
            question_log.prune(Path(folder), today=datetime.date(2026, 9, 25))
            self.assertEqual((old.exists(), kept.exists(), other.exists()), (False, True, True))

    def test_recording_prunes_old_files(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "discord-20250101.jsonl"
            old.write_text("{}\n", encoding="utf-8")
            question_log.record(question_log.entry(question="q", source="text", kind="chart"),
                                when=WHEN, folder=Path(folder))
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
