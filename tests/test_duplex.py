"""Checks the command protocol spoken to the two-way audio helper."""

from pathlib import Path
import os
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import duplex  # noqa: E402
import listen  # noqa: E402

WAIT_SECONDS = 2.0


class FakeProcess:
    """ตัวช่วยปลอม อ่านคำสั่งที่ถูกส่งได้ และป้อนรายงานกลับได้เอง"""

    def __init__(self) -> None:
        report_read, self._report_write = os.pipe()
        audio_read, self._audio_write = os.pipe()
        self.stderr = os.fdopen(report_read, "rb")
        self.stdout = os.fdopen(audio_read, "rb")
        self.stdin = _Recorder()
        self._exit: int | None = None

    def report(self, line: str) -> None:
        os.write(self._report_write, f"{line}\n".encode("utf-8"))

    def send_audio(self, payload: bytes) -> None:
        os.write(self._audio_write, payload)

    def poll(self) -> int | None:
        return self._exit

    def terminate(self) -> None:
        self._exit = 0

    def close(self) -> None:
        for handle in (self._report_write, self._audio_write):
            try:
                os.close(handle)
            except OSError:
                pass


class _Recorder:
    """ฝั่งเขียนคำสั่งแบบจำไว้ทั้งหมด"""

    def __init__(self) -> None:
        self.written = b""

    def write(self, payload: bytes) -> None:
        self.written += payload

    def flush(self) -> None:
        pass

    @property
    def commands(self) -> list[str]:
        return self.written.decode("utf-8").splitlines()


class VoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process = FakeProcess()
        self.voice = duplex.Voice(self.process)
        self.addCleanup(self.process.close)

    def test_the_ready_report_unblocks_the_waiter(self):
        self.process.report("ready")
        self.assertTrue(self.voice.wait_ready(WAIT_SECONDS))

    def test_playing_sends_a_command_and_waits_for_that_token(self):
        finished = threading.Event()
        threading.Thread(target=lambda: (self.voice.play(b"audio"), finished.set()),
                         daemon=True).start()
        deadline = time.monotonic() + WAIT_SECONDS
        while not self.process.stdin.commands and time.monotonic() < deadline:
            time.sleep(0.01)
        command = self.process.stdin.commands[0].split(" ")
        self.assertEqual(command[0], "play")
        self.assertFalse(finished.is_set())
        self.process.report(f"done {command[1]}")
        self.assertTrue(finished.wait(WAIT_SECONDS))

    def test_the_temporary_file_is_removed_after_playing(self):
        threading.Thread(target=lambda: self.voice.play(b"audio"), daemon=True).start()
        deadline = time.monotonic() + WAIT_SECONDS
        while not self.process.stdin.commands and time.monotonic() < deadline:
            time.sleep(0.01)
        parts = self.process.stdin.commands[0].split(" ", 2)
        self.process.report(f"done {parts[1]}")
        for _ in range(int(WAIT_SECONDS / 0.01)):
            if not os.path.exists(parts[2]):
                break
            time.sleep(0.01)
        self.assertFalse(os.path.exists(parts[2]))

    def test_stopping_releases_a_sentence_that_never_finished(self):
        finished = threading.Event()
        threading.Thread(target=lambda: (self.voice.play(b"audio"), finished.set()),
                         daemon=True).start()
        deadline = time.monotonic() + WAIT_SECONDS
        while not self.process.stdin.commands and time.monotonic() < deadline:
            time.sleep(0.01)
        self.voice.stop()
        self.assertTrue(finished.wait(WAIT_SECONDS))
        self.assertIn("stop", self.process.stdin.commands)

    def test_a_dead_helper_does_not_leave_anyone_waiting(self):
        finished = threading.Event()
        threading.Thread(target=lambda: (self.voice.play(b"audio"), finished.set()),
                         daemon=True).start()
        deadline = time.monotonic() + WAIT_SECONDS
        while not self.process.stdin.commands and time.monotonic() < deadline:
            time.sleep(0.01)
        self.process.close()
        self.assertTrue(finished.wait(WAIT_SECONDS))

    def test_audio_arrives_as_frames_of_the_expected_size(self):
        import numpy

        payload = numpy.full(listen.FRAME_SAMPLES * 2, 0.25, dtype=numpy.float32)
        self.process.send_audio(payload.tobytes())
        stream = self.voice.frames()
        first = next(stream)
        self.assertEqual(len(first), listen.FRAME_SAMPLES)
        self.assertAlmostEqual(float(first[0]), 0.25, places=6)

    def test_silence_only_audio_is_treated_as_a_broken_unit(self):
        import numpy

        silence = numpy.zeros(listen.FRAME_SAMPLES * listen.SILENCE_PROBE_FRAMES,
                              dtype=numpy.float32)
        self.process.send_audio(silence.tobytes())
        self.assertIsNone(duplex.probe(self.voice))


if __name__ == "__main__":
    unittest.main()
