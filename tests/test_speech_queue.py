"""Checks that the player reports itself busy until the last sentence really ends."""

from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import speak  # noqa: E402

PLAY_SECONDS = 0.15


class SpeechQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.played: list[bytes] = []
        self.started = threading.Event()
        original = speak.play
        self.addCleanup(lambda: setattr(speak, "play", original))
        speak.play = self.fake_play

    def fake_play(self, audio, register=None) -> None:
        self.started.set()
        time.sleep(PLAY_SECONDS)
        self.played.append(audio)

    def test_a_queued_sentence_counts_as_busy_before_playback_starts(self):
        player = speak.SpeechQueue()
        player.add(b"one")
        self.assertTrue(player.busy)
        player.close()

    def test_waiting_for_idle_returns_only_after_every_sentence_played(self):
        player = speak.SpeechQueue()
        player.add(b"one")
        player.add(b"two")
        self.assertTrue(player.wait_idle(timeout=5.0))
        self.assertEqual(self.played, [b"one", b"two"])
        self.assertFalse(player.busy)
        player.close()

    def test_a_player_with_nothing_queued_is_idle_at_once(self):
        player = speak.SpeechQueue()
        self.assertTrue(player.wait_idle(timeout=0.5))
        self.assertFalse(player.busy)
        player.close()

    def test_interrupting_clears_the_queue_and_stops_being_busy(self):
        player = speak.SpeechQueue()
        for _ in range(4):
            player.add(b"x")
        self.assertTrue(self.started.wait(1.0))
        player.interrupt()
        self.assertTrue(player.wait_idle(timeout=5.0))
        self.assertFalse(player.busy)
        self.assertLess(len(self.played), 4)
        player.close()

    def test_nothing_is_queued_after_an_interrupt(self):
        player = speak.SpeechQueue()
        player.interrupt()
        player.add(b"late")
        self.assertFalse(player.busy)
        player.close()
        self.assertEqual(self.played, [])


if __name__ == "__main__":
    unittest.main()
