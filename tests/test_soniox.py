"""Checks for the Soniox cloud speech-recognition client."""

from pathlib import Path
from unittest import mock
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import keys  # noqa: E402
import soniox_api  # noqa: E402


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_) -> bool:
        return False


def transcript_flow(tokens: list[dict], polls: list[dict] | None = None) -> list[FakeResponse]:
    """The four calls one file needs: upload, create, one poll, fetch."""
    stages = polls if polls is not None else [{"status": "completed", "audio_duration_ms": 4550}]
    return [
        FakeResponse({"id": "file-1"}),
        FakeResponse({"id": "job-1", "status": "queued"}),
        *[FakeResponse(stage) for stage in stages],
        FakeResponse({"tokens": tokens}),
        FakeResponse(b""),
        FakeResponse(b""),
    ]


class ApiKeyTests(unittest.TestCase):
    def test_the_environment_wins_over_the_env_file(self):
        with mock.patch.dict(soniox_api.os.environ, {"SONIOX_API": "from-env"}, clear=False):
            self.assertEqual(soniox_api.load_api_key(), "from-env")

    def test_a_missing_key_names_the_variable_it_wants(self):
        with mock.patch.dict(soniox_api.os.environ, {}, clear=True):
            with mock.patch.object(keys, "ROOT", Path("/nonexistent")):
                with self.assertRaises(SystemExit) as raised:
                    soniox_api.load_api_key()
        self.assertIn("SONIOX_API", str(raised.exception))

    def test_quotes_around_a_value_in_the_env_file_are_stripped(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / ".env").write_text('SONIOX_API="snx-quoted"\n', encoding="utf-8")
            with mock.patch.dict(soniox_api.os.environ, {}, clear=True):
                with mock.patch.object(keys, "ROOT", Path(folder)):
                    self.assertEqual(soniox_api.load_api_key(), "snx-quoted")


class ContextTests(unittest.TestCase):
    def test_glossary_terms_are_offered_to_the_model(self):
        context = soniox_api.transcription_context()
        self.assertIn("Check-raise", context["terms"])

    def test_the_domain_is_stated_so_the_model_knows_the_jargon(self):
        general = {item["key"]: item["value"] for item in
                   soniox_api.transcription_context()["general"]}
        self.assertEqual(general["domain"], soniox_api.DOMAIN)


class WavTests(unittest.TestCase):
    def test_float_samples_become_a_readable_mono_16k_wav(self):
        import numpy

        samples = numpy.zeros(1600, dtype=numpy.float32)
        samples[:8] = 1.0
        data = soniox_api.wav_bytes(samples)
        with wave.open(io.BytesIO(data)) as handle:
            self.assertEqual(handle.getframerate(), soniox_api.SAMPLE_RATE)
            self.assertEqual(handle.getnchannels(), 1)
            self.assertEqual(handle.getsampwidth(), 2)
            self.assertEqual(handle.getnframes(), 1600)

    def test_samples_beyond_full_scale_are_clipped_not_wrapped(self):
        import numpy

        data = soniox_api.wav_bytes(numpy.array([4.0, -4.0], dtype=numpy.float32))
        with wave.open(io.BytesIO(data)) as handle:
            frames = numpy.frombuffer(handle.readframes(2), dtype="<i2")
        self.assertEqual(frames[0], 32767)
        self.assertEqual(frames[1], -32767)


class TranscribeTests(unittest.TestCase):
    def test_tokens_are_joined_into_one_line_of_speech(self):
        flow = transcript_flow([{"text": "เจอ "}, {"text": "c-bet"}])
        with mock.patch.object(soniox_api.urllib.request, "urlopen", side_effect=flow):
            result = soniox_api.transcribe_bytes(b"wav", "key")
        self.assertEqual(result.text, "เจอ c-bet")

    def test_the_reported_audio_length_comes_from_the_service(self):
        flow = transcript_flow([{"text": "ok"}])
        with mock.patch.object(soniox_api.urllib.request, "urlopen", side_effect=flow):
            result = soniox_api.transcribe_bytes(b"wav", "key")
        self.assertAlmostEqual(result.audio_seconds, 4.55)

    def test_the_uploaded_file_and_the_job_are_both_cleaned_up(self):
        flow = transcript_flow([{"text": "ok"}])
        with mock.patch.object(soniox_api.urllib.request, "urlopen", side_effect=flow) as opened:
            soniox_api.transcribe_bytes(b"wav", "key")
        methods = [call.args[0].get_method() for call in opened.call_args_list]
        self.assertEqual(methods.count("DELETE"), 2)

    def test_a_job_that_fails_raises_with_the_reason_the_service_gave(self):
        flow = transcript_flow([], polls=[{"status": "error",
                                           "error_message": "Organization balance exhausted"}])
        with mock.patch.object(soniox_api.urllib.request, "urlopen", side_effect=flow):
            with self.assertRaises(soniox_api.SonioxError) as raised:
                soniox_api.transcribe_bytes(b"wav", "key")
        self.assertIn("balance exhausted", str(raised.exception))

    def test_a_queued_job_is_polled_until_it_finishes(self):
        flow = transcript_flow([{"text": "ok"}], polls=[
            {"status": "queued"}, {"status": "processing"}, {"status": "completed"}])
        with mock.patch.object(soniox_api.time, "sleep"):
            with mock.patch.object(soniox_api.urllib.request, "urlopen",
                                   side_effect=flow) as opened:
                result = soniox_api.transcribe_bytes(b"wav", "key")
        self.assertEqual(result.text, "ok")
        self.assertEqual(opened.call_count, len(flow))

    def test_a_transient_network_failure_is_retried(self):
        flow = transcript_flow([{"text": "ok"}])
        with mock.patch.object(soniox_api.time, "sleep"):
            with mock.patch.object(soniox_api.urllib.request, "urlopen",
                                   side_effect=[urllib.error.URLError("reset"), *flow]):
                result = soniox_api.transcribe_bytes(b"wav", "key")
        self.assertEqual(result.text, "ok")

    def test_a_rejected_key_is_not_retried(self):
        error = urllib.error.HTTPError("url", 401, "no", {}, io.BytesIO(b"bad key"))
        with mock.patch.object(soniox_api.urllib.request, "urlopen", side_effect=error) as opened:
            with self.assertRaises(soniox_api.SonioxError):
                soniox_api.transcribe_bytes(b"wav", "key")
        self.assertEqual(opened.call_count, 1)


if __name__ == "__main__":
    unittest.main()
