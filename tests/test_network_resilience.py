"""Checks that transient network failures retry instead of ending the session."""

from pathlib import Path
from unittest import mock
import sys
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import speak  # noqa: E402


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_) -> bool:
        return False


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("url", code, "boom", {}, None)


class SynthesisRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(speak.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_transient_failure_is_retried_and_can_succeed(self):
        attempts = [urllib.error.URLError("reset"), FakeResponse(b"audio")]
        with mock.patch.object(speak.urllib.request, "urlopen", side_effect=attempts) as opened:
            audio, _ = speak.synthesize("ทดสอบ", "lukchup", "key")
        self.assertEqual(audio, b"audio")
        self.assertEqual(opened.call_count, 2)

    def test_repeated_failures_raise_speech_error_not_system_exit(self):
        with mock.patch.object(speak.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("down")):
            with self.assertRaises(speak.SpeechError):
                speak.synthesize("ทดสอบ", "lukchup", "key")

    def test_all_attempts_are_used_before_giving_up(self):
        with mock.patch.object(speak.urllib.request, "urlopen",
                               side_effect=OSError("ssl eof")) as opened:
            with self.assertRaises(speak.SpeechError):
                speak.synthesize("ทดสอบ", "lukchup", "key")
        self.assertEqual(opened.call_count, speak.RETRIES)

    def test_a_client_error_is_not_retried(self):
        with mock.patch.object(speak.urllib.request, "urlopen",
                               side_effect=http_error(401)) as opened:
            with self.assertRaises(speak.SpeechError):
                speak.synthesize("ทดสอบ", "lukchup", "key")
        self.assertEqual(opened.call_count, 1)

    def test_a_server_error_is_retried(self):
        with mock.patch.object(speak.urllib.request, "urlopen",
                               side_effect=http_error(503)) as opened:
            with self.assertRaises(speak.SpeechError):
                speak.synthesize("ทดสอบ", "lukchup", "key")
        self.assertEqual(opened.call_count, speak.RETRIES)

    def test_rate_limiting_is_retried(self):
        with mock.patch.object(speak.urllib.request, "urlopen",
                               side_effect=http_error(429)) as opened:
            with self.assertRaises(speak.SpeechError):
                speak.synthesize("ทดสอบ", "lukchup", "key")
        self.assertEqual(opened.call_count, speak.RETRIES)

    def test_overlong_text_fails_without_calling_the_service(self):
        with mock.patch.object(speak.urllib.request, "urlopen") as opened:
            with self.assertRaises(speak.SpeechError):
                speak.synthesize("ก" * (speak.MAX_CHARS + 1), "lukchup", "key")
        opened.assert_not_called()
