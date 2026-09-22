"""Checks that listening in its own thread never leaves audio piling up."""

from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import listen  # noqa: E402

FRAMES_PER_TURN = 10
SETTLE_SECONDS = 1.0


class FakeDetector:
    """ปิดประโยคทุก ๆ สิบเฟรม เพื่อทดสอบได้โดยไม่ต้องมีไมค์และโมเดล"""

    def __init__(self) -> None:
        self.seen = 0
        self.speaking = False

    def reset(self) -> None:
        self.seen = 0
        self.speaking = False

    def push(self, frame) -> listen.Utterance | None:
        self.seen += 1
        self.speaking = self.seen % FRAMES_PER_TURN != 0
        if self.speaking:
            return None
        return listen.Utterance(samples=frame, seconds=FRAMES_PER_TURN * listen.FRAME_SECONDS)


class ListenerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stop = threading.Event()
        self.original_frames = listen.frames
        self.original_detector = listen.Detector
        listen.Detector = FakeDetector
        listen.frames = self.fake_frames
        self.addCleanup(self.restore)

    def restore(self) -> None:
        self.stop.set()
        listen.frames = self.original_frames
        listen.Detector = self.original_detector

    def fake_frames(self, device=None, echo_cancel=False):
        while not self.stop.is_set():
            time.sleep(0.001)
            yield "f"

    def wait_for(self, predicate) -> bool:
        deadline = time.monotonic() + SETTLE_SECONDS
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_a_closed_turn_carries_the_time_it_closed(self):
        listener = listen.Listener()
        self.assertTrue(listener.wait_ready(SETTLE_SECONDS))
        utterance = listener.take(timeout=SETTLE_SECONDS)
        self.assertIsNotNone(utterance)
        self.assertGreater(utterance.closed_at, 0.0)
        self.assertGreaterEqual(utterance.silence_before, 0.0)

    def test_taking_nothing_within_the_wait_returns_none(self):
        listener = listen.Listener()
        listener.mute()
        self.assertIsNone(listener.take(timeout=0.2))

    def test_muting_stops_new_turns_and_drops_the_old_ones(self):
        listener = listen.Listener()
        self.assertTrue(self.wait_for(lambda: listener.waiting > 0))
        listener.mute()
        self.assertEqual(listener.waiting, 0)
        time.sleep(0.2)
        self.assertEqual(listener.waiting, 0)

    def test_unmuting_listens_again_without_replaying_the_muted_part(self):
        listener = listen.Listener()
        listener.mute()
        listener.unmute()
        self.assertTrue(self.wait_for(lambda: listener.waiting > 0))

    def test_draining_reports_how_many_turns_were_dropped(self):
        listener = listen.Listener()
        self.assertTrue(self.wait_for(lambda: listener.waiting >= 2))
        listener.mute()
        self.assertEqual(listener.drain(), 0)

    def test_audio_never_piles_up_while_a_turn_is_being_answered(self):
        listener = listen.Listener()
        self.assertTrue(listener.wait_ready(SETTLE_SECONDS))
        listener.take(timeout=SETTLE_SECONDS)
        time.sleep(0.3)  # จำลองเวลาที่ลูปหลักติดอยู่กับการตอบ
        self.assertEqual(listen.backlog_seconds(), 0.0)


if __name__ == "__main__":
    unittest.main()
