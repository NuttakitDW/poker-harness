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


class FakePlayer:
    def __init__(self) -> None:
        self.stopped = threading.Event()

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


if __name__ == "__main__":
    unittest.main()
