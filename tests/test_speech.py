"""Checks that the conversation loop can swap speech providers safely."""

from pathlib import Path
from unittest import mock
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import soniox_tts  # noqa: E402
import speak  # noqa: E402
import speech  # noqa: E402


class ProviderTests(unittest.TestCase):
    def test_every_provider_has_a_default_voice(self):
        for provider in speech.PROVIDERS:
            self.assertTrue(speech.default_voice(provider))

    def test_an_unknown_provider_is_refused_before_any_call(self):
        with self.assertRaises(speech.SpeechError):
            speech.synthesizer("whoever")

    def test_soniox_goes_through_the_streaming_path(self):
        with mock.patch.object(soniox_tts, "stream_synthesize",
                               return_value=(b"audio", 1.0)) as streamed:
            with mock.patch.object(soniox_tts, "synthesize") as rest:
                speak_text = speech.synthesizer("soniox", key="k")
                self.assertEqual(speak_text("ทดสอบ"), (b"audio", 1.0))
        streamed.assert_called_once_with("ทดสอบ", speech.default_voice("soniox"), "k")
        rest.assert_not_called()

    def test_paxa_still_goes_through_its_own_synthesis(self):
        with mock.patch.object(speak, "synthesize", return_value=(b"paxa", 0.3)) as called:
            speak_text = speech.synthesizer("paxa", voice="lukchup", key="k")
            self.assertEqual(speak_text("ทดสอบ"), (b"paxa", 0.3))
        called.assert_called_once_with("ทดสอบ", "lukchup", "k")

    def test_a_provider_failure_arrives_as_one_shared_error_type(self):
        with mock.patch.object(soniox_tts, "stream_synthesize",
                               side_effect=soniox_tts.SpeechError("สายขาด")):
            speak_text = speech.synthesizer("soniox", key="k")
            with self.assertRaises(speech.SpeechError) as raised:
                speak_text("ทดสอบ")
        self.assertIn("สายขาด", str(raised.exception))

    def test_the_key_is_loaded_once_not_per_sentence(self):
        with mock.patch.object(soniox_tts, "load_api_key", return_value="k") as loaded:
            with mock.patch.object(soniox_tts, "stream_synthesize", return_value=(b"a", 1.0)):
                speak_text = speech.synthesizer("soniox")
                speak_text("หนึ่ง")
                speak_text("สอง")
        self.assertEqual(loaded.call_count, 1)


if __name__ == "__main__":
    unittest.main()
