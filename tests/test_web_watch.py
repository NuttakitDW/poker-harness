"""Checks the terminal that follows the website's Vercel logs and keeps its questions."""

import datetime
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "web"))
import watch  # noqa: E402
import question_log  # noqa: E402

# 2026-09-27 07:58:51 UTC
STAMP = 1790495931207


def vercel_line(message, level="info", row="1", stamp=STAMP):
    return json.dumps({"level": level, "message": message, "rowId": row, "source": "function",
                       "timestampInMs": stamp, "requestPath": "/api/ask", "domain": "tamkwai.com"})


def asked(question="BB เจอ BTN ออลอิน 8bb", kind="chart", **fields):
    return json.dumps({"at": "2026-09-27T07:58:51", "question": question, "source": "text",
                       "kind": kind, "parsed": {"hero": "BB", "stack": 8}, "server": "web",
                       "channel": None, **fields}, ensure_ascii=False)


class ReadTests(unittest.TestCase):
    def test_a_question_line_becomes_a_question(self):
        event = watch.read(vercel_line(asked()))
        self.assertEqual((event.kind, event.entry["question"]), ("question", "BB เจอ BTN ออลอิน 8bb"))
        self.assertEqual(event.when, datetime.datetime.fromtimestamp(STAMP / 1000))

    def test_access_log_lines_are_skipped(self):
        line = vercel_line('127.0.0.1 - - [27/Sep/2026 07:58:51] "POST /api/ask?path=ask HTTP/1.1" 200 -')
        self.assertIsNone(watch.read(line))

    def test_errors_and_cold_starts_are_kept(self):
        self.assertEqual(watch.read(vercel_line("Traceback (most recent call last):", level="error")).kind, "error")
        self.assertEqual(watch.read(vercel_line("tamkwai web cold start: raqm=True")).kind, "start")

    def test_broken_lines_are_skipped(self):
        for raw in ("", "not json", "[]", json.dumps({"message": 3})):
            with self.subTest(raw=raw):
                self.assertIsNone(watch.read(raw))


class ShowTests(unittest.TestCase):
    def test_a_question_shows_its_time_kind_and_text(self):
        text = watch.show(watch.read(vercel_line(asked())), color=False)
        self.assertIn("chart", text)
        self.assertIn("BB เจอ BTN ออลอิน 8bb", text)
        self.assertIn(datetime.datetime.fromtimestamp(STAMP / 1000).strftime("%H:%M:%S"), text)

    def test_the_ai_query_is_shown_when_it_differs(self):
        text = watch.show(watch.read(vercel_line(asked(ai_query="BB vs BTN shove 8bb"))), color=False)
        self.assertIn("AI → BB vs BTN shove 8bb", text)

    def test_a_screenshot_is_marked(self):
        text = watch.show(watch.read(vercel_line(asked(source="image"))), color=False)
        self.assertIn("[รูป]", text)


class FollowTests(unittest.TestCase):
    def test_questions_are_printed_saved_and_not_repeated(self):
        lines = [vercel_line(asked(), row="1"), vercel_line("noise"), vercel_line(asked(), row="1"),
                 vercel_line(asked("SB 6bb", kind="not_found"), row="2")]
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            seen = watch.Seen()
            count = watch.consume(lines, seen, Path(folder), out, color=False)
            saved = [json.loads(row) for path in Path(folder).glob("web-*.jsonl")
                     for row in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(count, 2)
        self.assertEqual([row["question"] for row in saved], ["BB เจอ BTN ออลอิน 8bb", "SB 6bb"])
        self.assertEqual(out.getvalue().count("BB เจอ BTN"), 1)

    def test_the_saved_time_is_when_vercel_logged_it(self):
        with tempfile.TemporaryDirectory() as folder:
            watch.consume([vercel_line(asked())], watch.Seen(), Path(folder), io.StringIO(), color=False)
            row = json.loads(next(Path(folder).glob("web-*.jsonl")).read_text(encoding="utf-8"))
        self.assertEqual(row["at"], datetime.datetime.fromtimestamp(STAMP / 1000).isoformat(timespec="seconds"))

    def test_the_seen_set_forgets_old_rows(self):
        seen = watch.Seen(limit=2)
        for row in ("a", "b", "c"):
            self.assertTrue(seen.first(row))
        self.assertFalse(seen.first("c"))
        self.assertTrue(seen.first("a"))



def history_row(question="BB เจอ BTN ออลอิน 8bb", request_id="req1", stamp=STAMP, **fields):
    """One row of `vercel logs --json`: a request with its log lines."""
    return json.dumps({"id": request_id, "timestamp": stamp, "level": "info", "domain": "tamkwai.com",
                       "requestPath": "/api/ask", "message": asked(question, **fields),
                       "logs": [{"level": "info", "message": asked(question, **fields)},
                                {"level": "info", "message": '127.0.0.1 - - "POST /api/ask HTTP/1.1" 200 -'}]},
                      ensure_ascii=False)


class HistoryTests(unittest.TestCase):
    """The past hour from `vercel logs` fills gaps: before the watcher started or while it reconnected."""

    def test_a_history_row_becomes_stream_lines(self):
        lines = watch.history_lines(history_row())
        events = [watch.read(line) for line in lines]
        self.assertEqual([event.kind for event in events if event], ["question"])

    def test_history_is_replayed_oldest_first(self):
        output = "\n".join((history_row("second", "b", STAMP + 5000), history_row("first", "a", STAMP)))
        lines = watch.backfill("1h", run=lambda args: output)
        questions = [watch.read(line).text for line in lines if watch.read(line)]
        self.assertEqual(questions, ["first", "second"])

    def test_the_history_asks_the_cli_for_production_questions(self):
        seen_args = []
        watch.backfill("15m", run=lambda args: seen_args.extend(args) or "")
        for flag in ("--since", "15m", "--environment", "production", "--no-branch", "--json"):
            self.assertIn(flag, seen_args)

    def test_a_missing_cli_raises_a_readable_error(self):
        def broken(args):
            raise FileNotFoundError("vercel")
        with self.assertRaises(watch.FetchError):
            watch.backfill("1h", run=broken)

    def test_a_question_seen_live_and_in_history_is_kept_once(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            seen = watch.Seen()
            watch.consume([vercel_line(asked(), row="live-1")], seen, Path(folder), out, color=False)
            watch.consume(watch.history_lines(history_row()), seen, Path(folder), out, color=False)
            rows = next(Path(folder).glob("web-*.jsonl")).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)

    def test_questions_saved_by_an_earlier_run_are_not_saved_again(self):
        with tempfile.TemporaryDirectory() as folder:
            watch.consume([vercel_line(asked())], watch.Seen(), Path(folder), io.StringIO(), color=False)
            again = watch.Seen.from_files(Path(folder))
            count = watch.consume(watch.history_lines(history_row()), again, Path(folder), io.StringIO(), color=False)
        self.assertEqual(count, 0)



class PollTests(unittest.TestCase):
    """The watcher polls `vercel logs` (history lands there ~16s after a question) instead of the live stream,
    which dropped lines around its 5-minute cutoff."""

    def run_polls(self, outputs, folder):
        calls, out = [], io.StringIO()
        replies = iter(outputs)

        def run(args):
            calls.append(args)
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

        def sleep(seconds):
            if len(calls) >= len(outputs):
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            watch.follow(Path(folder), out, run=run, sleep=sleep, clock=lambda: 0.0)
        return calls, out.getvalue()

    def test_the_first_poll_is_the_past_hour_of_questions_then_short_windows(self):
        with tempfile.TemporaryDirectory() as folder:
            calls, _ = self.run_polls(["", "", ""], folder)
        self.assertEqual(calls[0][calls[0].index("--since") + 1], "1h")
        self.assertIn("--query", calls[0])
        self.assertEqual(calls[1][calls[1].index("--since") + 1], "2m")
        self.assertNotIn("--query", calls[1])  # live polls also show errors and cold starts

    def test_a_question_seen_in_two_overlapping_polls_prints_once(self):
        row = history_row("SB 6bb", "req9", STAMP)
        with tempfile.TemporaryDirectory() as folder:
            _, printed = self.run_polls(["", row, row], folder)
        self.assertEqual(printed.count("SB 6bb"), 1)

    def test_old_cold_starts_are_not_replayed_but_new_ones_are_shown(self):
        start = json.dumps({"id": "req2", "timestamp": STAMP, "logs": [
            {"level": "info", "message": "tamkwai web cold start: raqm=False"}]})
        with tempfile.TemporaryDirectory() as folder:
            _, printed = self.run_polls([start, start], folder)
        self.assertEqual(printed.count("cold start"), 1)

    def test_a_failing_cli_is_reported_once_and_polling_goes_on(self):
        failure = subprocess.CalledProcessError(1, "vercel", stderr="Error: not logged in")
        with tempfile.TemporaryDirectory() as folder:
            _, printed = self.run_polls([failure, failure, history_row("BTN 10bb", "r1")], folder)
        self.assertEqual(printed.count("not logged in"), 1)
        self.assertIn("BTN 10bb", printed)


class WebLogFileTests(unittest.TestCase):
    def test_web_questions_get_their_own_daily_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = question_log.record({"question": "x", "kind": "chart"},
                                       when=datetime.datetime(2026, 9, 27, 15, 0), folder=Path(folder),
                                       prefix="web")
        self.assertEqual(path.name, "web-20260927.jsonl")

    def test_old_web_files_are_pruned_too(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "web-20260101.jsonl"
            old.write_text("{}\n")
            question_log.prune(Path(folder), datetime.date(2026, 9, 27), prefix="web")
            self.assertFalse(old.exists())

    def test_the_review_reads_web_misses(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "web-20260927.jsonl").write_text(
                json.dumps({"at": "t", "question": "??", "kind": "not_found"}) + "\n"
                + json.dumps({"at": "t", "question": "BTN 10bb", "kind": "chart"}) + "\n")
            rows = question_log.misses(Path(folder), prefix="web")
        self.assertEqual([row["question"] for row in rows], ["??"])


if __name__ == "__main__":
    unittest.main()
