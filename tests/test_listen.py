"""Checks for deciding when a spoken turn has ended."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import listen  # noqa: E402

SILENCE_FRAMES = int(listen.END_SILENCE_SECONDS / listen.FRAME_SECONDS) + 1


def run(speech_frames: int, silence_frames: int = SILENCE_FRAMES) -> list | None:
    """ป้อนเสียงพูดตามด้วยความเงียบ คืนประโยคที่ปิดได้ หรือ None"""
    endpointer = listen.Endpointer()
    for _ in range(speech_frames):
        endpointer.push("f", True)
    for _ in range(silence_frames):
        closed = endpointer.push("f", False)
        if closed is not None:
            return closed
    return None


class TurnStartTests(unittest.TestCase):
    def test_a_single_speech_frame_does_not_start_a_turn(self):
        endpointer = listen.Endpointer()
        endpointer.push("f", True)
        self.assertFalse(endpointer.speaking)

    def test_enough_consecutive_frames_start_a_turn(self):
        endpointer = listen.Endpointer()
        for _ in range(listen.START_FRAMES):
            endpointer.push("f", True)
        self.assertTrue(endpointer.speaking)

    def test_isolated_speech_frames_do_not_accumulate(self):
        endpointer = listen.Endpointer()
        for _ in range(10):
            endpointer.push("f", True)
            endpointer.push("f", False)
        self.assertFalse(endpointer.speaking)


class TurnEndTests(unittest.TestCase):
    def test_brief_noise_is_discarded(self):
        self.assertIsNone(run(4))

    def test_a_real_utterance_is_returned(self):
        closed = run(30)
        self.assertIsNotNone(closed)
        self.assertGreater(len(closed), 30)

    def test_short_silence_does_not_end_the_turn(self):
        self.assertIsNone(run(30, silence_frames=3))

    def test_preroll_is_included_so_the_first_word_survives(self):
        closed = run(30)
        self.assertGreater(len(closed), 30 + SILENCE_FRAMES - 2)

    def test_state_resets_after_a_turn_closes(self):
        endpointer = listen.Endpointer()
        for _ in range(30):
            endpointer.push("f", True)
        for _ in range(SILENCE_FRAMES):
            if endpointer.push("f", False) is not None:
                break
        self.assertFalse(endpointer.speaking)
        self.assertEqual(endpointer.seconds, 0.0)

    def test_a_very_long_turn_is_cut_at_the_limit(self):
        endpointer = listen.Endpointer()
        limit = int(listen.MAX_UTTERANCE_SECONDS / listen.FRAME_SECONDS) + 5
        closed = None
        for _ in range(limit):
            closed = endpointer.push("f", True)
            if closed is not None:
                break
        self.assertIsNotNone(closed)
