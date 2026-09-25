"""Checks the Paxa speech-to-text client without touching the network."""

import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import costs  # noqa: E402
import paxa_stt  # noqa: E402


def final(text):
    return {"type": "transcript", "is_final": True, "text": text}


def interim(text):
    return {"type": "transcript", "is_final": False, "text": text}


class TurnsTests(unittest.TestCase):
    def test_a_turn_closes_after_the_join_window(self):
        turns = paxa_stt.Turns(join_seconds=0.9)
        turns.push({"type": "speech_started"}, 0.0)
        turns.push(final("BTN all in"), 1.0)
        self.assertIsNone(turns.due(1.5))
        self.assertEqual(turns.due(2.0), "BTN all in")
        self.assertIsNone(turns.due(3.0))

    def test_turns_split_by_a_short_pause_join_into_one_question(self):
        turns = paxa_stt.Turns(join_seconds=0.9)
        turns.push(final("บัตตัน all in"), 1.0)
        turns.push({"type": "speech_started"}, 1.4)
        self.assertIsNone(turns.due(2.5))  # still speaking the second half
        turns.push(final("10 big blind ถือ AK"), 3.0)
        self.assertEqual(turns.due(4.0), "บัตตัน all in 10 big blind ถือ AK")

    def test_interim_text_shows_in_the_partial_but_not_in_the_sentence(self):
        turns = paxa_stt.Turns()
        turns.push(final("SB"), 0.0)
        turns.push(interim("เจอ UTG"), 0.1)
        self.assertEqual(turns.partial, "SB เจอ UTG")
        self.assertTrue(turns.speaking)

    def test_an_empty_turn_gives_no_sentence(self):
        turns = paxa_stt.Turns(join_seconds=0.5)
        turns.push(final(""), 0.0)
        self.assertIsNone(turns.due(1.0))


class RequestTests(unittest.TestCase):
    def test_the_vocabulary_fits_the_limits_and_puts_seats_first(self):
        terms = paxa_stt.vocabulary()
        self.assertLessEqual(len(terms), 50)
        self.assertTrue(all(len(term) <= 50 for term in terms))
        self.assertEqual(terms[:4], ["UTG", "Lojack", "Hijack", "Cutoff"])

    def test_the_stream_asks_for_digits_and_clean_text(self):
        start = paxa_stt.start_message()
        self.assertEqual(start["type"], "start")
        self.assertEqual(start["audio"], {"encoding": "pcm_s16le", "sample_rate": 16000})
        self.assertEqual((start["convention"], start["style"]), ("written", "clean"))

    def test_a_voice_message_is_sent_as_base64_and_its_text_returned(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen.update(json.loads(request.data))
            return io.StringIO(json.dumps({"text": " SB shove 5bb "}))

        with mock.patch.object(paxa_stt.urllib.request, "urlopen", fake_urlopen):
            result = paxa_stt.transcribe_bytes(b"OggS...", "k", "voice-message.ogg")
        self.assertEqual(result.text, "SB shove 5bb")
        self.assertEqual(seen["model"], paxa_stt.BATCH_MODEL)
        self.assertEqual(seen["convention"], "written")

    def test_an_http_error_is_reported_with_its_code(self):
        error = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b'{"code":"bad_key"}'))
        with mock.patch.object(paxa_stt.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(paxa_stt.PaxaError, "401"):
                paxa_stt.transcribe_bytes(b"x", "k")


class CostTests(unittest.TestCase):
    def test_paxa_streaming_is_charged_at_its_own_rate(self):
        self.assertAlmostEqual(costs.stream_usd("paxa-stt-rt", 60.0), costs.paxa_stt_usd(60.0))
        self.assertAlmostEqual(costs.stream_usd("soniox-stt-rt", 60.0), costs.soniox_stt_usd(60.0))
        self.assertGreater(costs.paxa_stt_usd(60.0), 0)


if __name__ == "__main__":
    unittest.main()
