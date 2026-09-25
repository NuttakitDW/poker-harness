"""The spot context goes only to spot-chart transcription; general voice keeps the glossary context."""

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))
import soniox_api  # noqa: E402
import soniox_rt  # noqa: E402


class ContextTests(unittest.TestCase):
    def test_the_general_context_is_the_default(self):
        context = soniox_api.transcription_context()
        self.assertNotIn("text", context)
        self.assertEqual(context, soniox_api.transcription_context("general"))

    def test_the_spot_context_puts_seat_words_first_and_shows_examples(self):
        context = soniox_api.transcription_context("spot")
        self.assertEqual(context["terms"][:3], ["UTG", "UTG+1", "Lojack"])
        self.assertIn("Button all-in 10 big blinds", context["text"])

    def test_an_unknown_context_fails_clearly(self):
        with self.assertRaises(ValueError):
            soniox_api.transcription_context("poker")

    def test_the_stream_config_carries_the_chosen_context(self):
        self.assertIn("text", soniox_rt._config("k", "spot")["context"])
        self.assertNotIn("text", soniox_rt._config("k")["context"])

    def test_file_transcription_sends_the_chosen_context(self):
        sent = []

        def fake_call(method, path, key, payload=None, **kwargs):
            if path == "/files":
                return {"id": "f"}
            if path == "/transcriptions" and method == "POST":
                sent.append(payload["context"])
                return {"id": "j"}
            return {"tokens": [{"text": "SB"}]}

        with mock.patch.object(soniox_api, "_call", fake_call), \
                mock.patch.object(soniox_api, "_await_transcript", return_value={}), \
                mock.patch.object(soniox_api, "_discard"):
            soniox_api.transcribe_bytes(b"x", "k", "voice.ogg", context="spot")
        self.assertIn("text", sent[0])


class CallerTests(unittest.TestCase):
    def test_the_chart_voice_mode_and_the_bot_ask_for_the_spot_context(self):
        chart = (ROOT / "scripts/voice/spot_chart.py").read_text(encoding="utf-8")
        bot = (ROOT / "scripts/discord_bot/bot.py").read_text(encoding="utf-8")
        self.assertIn('context="spot"', chart)
        self.assertIn('"spot"', bot.split("soniox_api.transcribe_bytes", 1)[1][:200])


if __name__ == "__main__":
    unittest.main()
