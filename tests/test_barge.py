"""Checks that Look Choop goes quiet the moment the user starts talking, not when they finish."""

from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import barge  # noqa: E402

WAIT_SECONDS = 1.0


class FakeListener:
    def __init__(self) -> None:
        self.speaking = False
        self.waiting = 0


class FakePlayer:
    def __init__(self) -> None:
        self.stopped = threading.Event()
        self.busy = True

    def interrupt(self) -> None:
        self.stopped.set()


class BargeWatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.listener = FakeListener()
        self.player = FakePlayer()
        self.watch = barge.BargeWatch(self.listener, self.player, poll=0.01)
        self.addCleanup(self.watch.stop)

    def test_silence_leaves_the_answer_playing(self):
        time.sleep(0.05)
        self.assertFalse(self.player.stopped.is_set())
        self.assertFalse(self.watch.fired)

    def test_speech_onset_stops_playback_before_the_sentence_ends(self):
        self.listener.speaking = True
        self.assertTrue(self.player.stopped.wait(WAIT_SECONDS))
        self.assertTrue(self.watch.fired)

    def test_stopping_the_watch_ignores_later_speech(self):
        self.watch.stop()
        self.listener.speaking = True
        time.sleep(0.05)
        self.assertFalse(self.player.stopped.is_set())
        self.assertFalse(self.watch.fired)

    def test_speaking_after_the_answer_finished_is_not_an_interruption(self):
        self.player.busy = False
        self.listener.speaking = True
        time.sleep(0.05)
        self.assertFalse(self.watch.fired)


class ClipTests(unittest.TestCase):
    def test_a_short_reply_is_kept_whole(self):
        self.assertEqual(barge.clip("ได้เลยค่ะ", limit=40), "ได้เลยค่ะ")

    def test_a_long_reply_is_cut_between_phrases(self):
        said = barge.clip("ได้เลยค่ะ เล่าไพ่กับสถานการณ์มาได้เลย ลูกชุบรอฟังอยู่", limit=20)
        self.assertEqual(said, "ได้เลยค่ะ")

    def test_a_single_long_phrase_is_not_cut_mid_word(self):
        phrase = "ก" * 50
        self.assertEqual(barge.clip(phrase, limit=20), phrase)


class HoldForMoreTests(unittest.TestCase):
    """คนที่เพิ่งพูดแทรกแล้วเว้นจังหวะคิด ต้องได้พูดต่อ ไม่ใช่โดนลูกชุบพูดสวน"""

    def test_a_real_pause_lets_the_reply_start(self):
        listener = FakeListener()
        began = time.monotonic()
        self.assertFalse(barge.hold_for_more(listener, began, hold=0.05, poll=0.01))
        self.assertGreaterEqual(time.monotonic() - began, 0.05)

    def test_resuming_speech_during_the_pause_keeps_listening(self):
        listener = FakeListener()
        threading.Timer(0.03, lambda: setattr(listener, "speaking", True)).start()
        self.assertTrue(barge.hold_for_more(listener, time.monotonic(), hold=0.5, poll=0.01))

    def test_a_queued_utterance_counts_as_still_talking(self):
        listener = FakeListener()
        listener.waiting = 1
        self.assertTrue(barge.hold_for_more(listener, time.monotonic(), hold=0.5, poll=0.01))

    def test_silence_that_already_lasted_long_enough_does_not_wait_again(self):
        listener = FakeListener()
        began = time.monotonic()
        self.assertFalse(barge.hold_for_more(listener, began - 1.0, hold=0.5, poll=0.01))
        self.assertLess(time.monotonic() - began, 0.05)


if __name__ == "__main__":
    unittest.main()
