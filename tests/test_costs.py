"""Checks that every paid call is priced and written to the session log."""

from pathlib import Path
from unittest import mock
import datetime
import io
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import brain  # noqa: E402
import cost_report  # noqa: E402
import costs  # noqa: E402
import journal  # noqa: E402
import speak  # noqa: E402

UTC = datetime.timezone.utc


class PriceTests(unittest.TestCase):
    def test_deepseek_charges_cached_input_far_below_fresh_input(self):
        cached = costs.deepseek_usd(hit=1_000_000, miss=0, output=0, peak=True)
        fresh = costs.deepseek_usd(hit=0, miss=1_000_000, output=0, peak=True)
        self.assertAlmostEqual(cached, 0.006)
        self.assertAlmostEqual(fresh, 0.30)

    def test_off_peak_is_half_price(self):
        peak = costs.deepseek_usd(hit=100, miss=5000, output=300, peak=True)
        off = costs.deepseek_usd(hit=100, miss=5000, output=300, peak=False)
        self.assertAlmostEqual(off * 2, peak)

    def test_peak_hours_follow_the_published_utc_windows(self):
        wednesday = datetime.datetime(2026, 9, 23, 2, 30, tzinfo=UTC)
        self.assertTrue(costs.is_peak(wednesday))
        self.assertFalse(costs.is_peak(wednesday.replace(hour=5)))
        self.assertFalse(costs.is_peak(datetime.datetime(2026, 9, 26, 2, 30, tzinfo=UTC)))

    def test_paxa_bills_per_character(self):
        self.assertAlmostEqual(costs.paxa_usd(1_000_000),
                               costs.PAXA_THB_PER_M_CHARS / costs.THB_PER_USD)

    def test_realtime_stt_bills_every_streamed_second(self):
        self.assertAlmostEqual(costs.soniox_stt_usd(3600, realtime=True), 0.12)
        self.assertAlmostEqual(costs.soniox_stt_usd(3600, realtime=False), 0.10)


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        costs.reset()
        self.addCleanup(costs.reset)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "log.jsonl"
        journal.start(self.path, echo=False)
        self.addCleanup(journal.stop)

    def records(self) -> list[dict]:
        journal.stop()
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_each_call_is_logged_and_added_to_the_session_total(self):
        costs.record("paxa-tts", 0.01, quantity=20, seconds=0.5)
        costs.record("paxa-tts", 0.02, quantity=40, seconds=0.7)
        costs.record("deepseek", 0.005, quantity=7000, seconds=1.2)
        self.assertEqual(costs.spent(), {"paxa-tts": 0.03, "deepseek": 0.005})
        self.assertEqual([r["api"] for r in self.records()],
                         ["paxa-tts", "paxa-tts", "deepseek"])

    def test_the_summary_is_a_copy_the_caller_cannot_change(self):
        costs.record("deepseek", 0.001, quantity=10, seconds=1)
        costs.spent()["deepseek"] = 99
        self.assertEqual(costs.spent(), {"deepseek": 0.001})

    def test_every_service_logs_the_same_fields(self):
        costs.record("paxa-tts", 0.01, quantity=20, seconds=0.5)
        costs.record("deepseek", 0.005, quantity=7000, seconds=1.2, hit=100)
        costs.record("soniox-stt-rt", 0.001, quantity=30, seconds=30)
        records = self.records()
        self.assertEqual([r["unit"] for r in records], ["char", "token", "second"])
        for record in records:
            self.assertLessEqual({"api", "usd", "unit", "quantity", "seconds"}, set(record))

    def test_the_open_stream_is_charged_only_for_new_seconds(self):
        billed = costs.charge_stream("soniox-stt-rt", 60.0, 0.0)
        billed = costs.charge_stream("soniox-stt-rt", 90.0, billed)
        billed = costs.charge_stream("soniox-stt-rt", 90.0, billed)
        self.assertEqual(billed, 90.0)
        tally = costs.tallies()["soniox-stt-rt"]
        self.assertEqual((tally.calls, tally.quantity), (2, 90.0))
        self.assertAlmostEqual(tally.usd, costs.soniox_stt_usd(90))

    def test_the_summary_carries_quantities_duration_and_hourly_rate(self):
        costs.record("paxa-tts", 0.01, quantity=20, seconds=0.5)
        costs.record("paxa-tts", 0.02, quantity=40, seconds=0.7)
        with mock.patch.object(costs.time, "monotonic", return_value=costs._began + 1800):
            summary = costs.summary(final=False)
        self.assertFalse(summary["final"])
        self.assertEqual(summary["session_seconds"], 1800)
        self.assertAlmostEqual(summary["usd_per_hour"], 0.06)
        self.assertEqual(summary["usage"]["paxa-tts"],
                         {"unit": "char", "quantity": 60, "calls": 2, "seconds": 1.2,
                          "usd": 0.03})

    def test_a_successful_speech_call_is_priced_by_characters(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"audio"
        with mock.patch.object(speak.urllib.request, "urlopen", return_value=response):
            speak.synthesize("สวัสดี", "lukchup", "key")
        usage = self.records()[0]
        self.assertEqual((usage["api"], usage["quantity"], usage["unit"]),
                         ("paxa-tts", 6, "char"))
        self.assertGreater(usage["usd"], 0)


def stream_lines(*chunks: dict) -> io.BytesIO:
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n"
    return io.BytesIO(body.encode("utf-8"))


class ModelUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        costs.reset()
        self.addCleanup(costs.reset)

    def test_the_request_asks_the_stream_to_report_usage(self):
        request = brain._request("q", "ctx", "key")
        self.assertTrue(json.loads(request.data)["stream_options"]["include_usage"])

    def test_reported_usage_is_priced(self):
        reply = stream_lines(
            {"choices": [{"delta": {"content": "ตอบ"}}]},
            {"choices": [], "usage": {"prompt_tokens": 7000, "completion_tokens": 250,
                                      "prompt_cache_hit_tokens": 2000,
                                      "prompt_cache_miss_tokens": 5000}})
        with mock.patch.object(brain, "_open_stream", return_value=reply), \
                mock.patch.object(costs, "record") as recorded:
            self.assertEqual("".join(brain.stream_model("q", "ctx", "key")), "ตอบ")
        fields = recorded.call_args.kwargs
        self.assertEqual((fields["miss"], fields["hit"], fields["output"]), (5000, 2000, 250))
        self.assertFalse(fields["estimated"])

    def test_an_answer_cut_short_is_still_charged_by_estimate(self):
        reply = stream_lines({"choices": [{"delta": {"content": "ตอบยาว"}}]},
                             {"choices": [{"delta": {"content": "ต่อ"}}]})
        with mock.patch.object(brain, "_open_stream", return_value=reply), \
                mock.patch.object(costs, "record") as recorded:
            pieces = brain.stream_model("q", "ctx" * 300, "key")
            next(pieces)
            pieces.close()
        fields = recorded.call_args.kwargs
        self.assertTrue(fields["estimated"])
        self.assertGreater(fields["miss"], 0)


class DescribeTests(unittest.TestCase):
    def test_the_session_total_is_shown_in_dollars_and_baht(self):
        line = journal.describe("cost", {"total_usd": 0.1, "total_thb": 3.3,
                                         "by_api": {"deepseek": 0.1},
                                         "session_seconds": 90.0, "usd_per_hour": 4.0})
        self.assertIn("$0.1000", line)
        self.assertIn("฿3.30", line)
        self.assertIn("90.00s", line)
        self.assertIn("$4.000/ชม.", line)

    def test_a_usage_line_shows_amount_and_time(self):
        line = journal.describe("usage", {"api": "deepseek", "usd": 0.002, "unit": "token",
                                          "quantity": 7250, "seconds": 1.4})
        self.assertIn("7250 token", line)
        self.assertIn("1.40s", line)


class ReportTests(unittest.TestCase):
    def write(self, *records: dict) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "live.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return path

    def test_counted_usage_is_summed_per_service(self):
        session = cost_report.summarize(self.write(
            {"kind": "usage", "api": "deepseek", "usd": 0.002, "since": 10},
            {"kind": "usage", "api": "deepseek", "usd": 0.003, "since": 20},
            {"kind": "answer", "text": "x", "since": 60}))
        self.assertFalse(session.estimated)
        self.assertAlmostEqual(session.by_api["deepseek"], 0.005)
        self.assertEqual((session.minutes, session.answers), (1.0, 1))

    def test_an_old_log_is_estimated_including_the_open_stream(self):
        session = cost_report.summarize(self.write(
            {"kind": "start", "engine": "soniox-rt", "tts": "paxa", "since": 0},
            {"kind": "answer", "text": "ก" * 100, "since": 3600}))
        self.assertTrue(session.estimated)
        self.assertAlmostEqual(session.by_api["soniox-stt-rt"], 0.12)
        self.assertGreater(session.by_api["paxa-tts"], 0)

    def test_the_report_projects_a_yearly_cost(self):
        text = cost_report.report([cost_report.Session("a", 60.0, 10, {"deepseek": 0.5}, False)])
        self.assertIn("ต่อชั่วโมงที่เปิดคุย $0.500", text)
        self.assertIn("ชม./ปี", text)


if __name__ == "__main__":
    unittest.main()
