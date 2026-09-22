"""คุยกับตัวช่วย Swift ที่เล่นเสียงและจับเสียงด้วยยูนิตเดียวกัน

เล่นเสียงตอบผ่านยูนิตเดียวกับที่จับเสียง ยูนิตจึงรู้ว่าลำโพงปล่อยอะไรออกไป
และลบออกจากสัญญาณไมค์ได้ ทำให้พูดแทรกได้โดยไม่ต้องใส่หูฟัง
ถ้าเครื่องไหนเปิดยูนิตนี้ไม่ได้ ผู้เรียกถอยไปใช้ไมค์ปกติกับ afplay ได้
"""

from __future__ import annotations

import contextlib
import itertools
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
from typing import Iterator

import journal
import listen

READY_TIMEOUT_SECONDS = 20.0
PLAY_TIMEOUT_SECONDS = 180.0


class Voice:
    """ตัวเล่นและตัวจับเสียงในกระบวนการเดียว

    เล่นเสียงแบบรอจนจบเพื่อให้ใช้แทน afplay ได้ตรง ๆ และสั่งหยุดกลางคันได้
    """

    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._waiting: dict[str, threading.Event] = {}
        self._tokens = itertools.count(1)
        self._reader = threading.Thread(target=self._read_reports, daemon=True)
        self._reader.start()

    def _read_reports(self) -> None:
        """อ่านรายงานจากตัวช่วย แล้วปลดคนที่รอเสียงชิ้นนั้นอยู่"""
        for raw in self._process.stderr:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            if line == "ready":
                self._ready.set()
                continue
            head, _, rest = line.partition(" ")
            if head == "done":
                self._finish(rest)
            else:
                print(f"[เสียงสองทาง] {line}", file=sys.stderr)
                journal.note("duplex", message=line)
        # ตัวช่วยตายแล้ว ห้ามปล่อยให้ใครค้างรอเสียงที่จะไม่มาอีก
        journal.note("duplex-ended", code=self._process.poll())
        self._ready.set()
        self.release()

    def _finish(self, token: str) -> None:
        with self._lock:
            waiter = self._waiting.get(token)
        if waiter:
            waiter.set()

    def _send(self, command: str) -> None:
        stdin = self._process.stdin
        if not stdin or self._process.poll() is not None:
            return
        with contextlib.suppress(OSError, ValueError):
            stdin.write(f"{command}\n".encode("utf-8"))
            stdin.flush()

    def release(self) -> None:
        """ปลดทุกคนที่รออยู่ ใช้ตอนหยุดกลางคันหรือตัวช่วยตาย"""
        with self._lock:
            waiters = list(self._waiting.values())
        for waiter in waiters:
            waiter.set()

    def wait_ready(self, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
        """รอจนตัวช่วยเปิดยูนิตเสียงสำเร็จ"""
        return self._ready.wait(timeout) and self._process.poll() is None

    @property
    def alive(self) -> bool:
        """ตัวช่วยยังทำงานอยู่หรือไม่"""
        return self._process.poll() is None

    def frames(self) -> Iterator["object"]:
        """เฟรมเสียงจากไมค์ที่ตัดเสียงสะท้อนออกแล้ว"""
        import numpy

        width = listen.FRAME_SAMPLES * 4
        stdout = self._process.stdout
        while stdout is not None:
            chunk = stdout.read(width)
            if not chunk or len(chunk) < width:
                return
            yield numpy.frombuffer(chunk, dtype=numpy.float32).copy()

    def play(self, audio: bytes) -> None:
        """เล่นเสียงหนึ่งชิ้นแล้วรอจนเล่นจบ ใช้แทน afplay ได้ตรง ๆ"""
        token = str(next(self._tokens))
        done = threading.Event()
        with self._lock:
            self._waiting[token] = done
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(audio)
            path = handle.name
        try:
            self._send(f"play {token} {path}")
            done.wait(PLAY_TIMEOUT_SECONDS)
        finally:
            with self._lock:
                self._waiting.pop(token, None)
            with contextlib.suppress(OSError):
                os.unlink(path)

    def stop(self) -> None:
        """หยุดเสียงที่กำลังเล่นและทิ้งที่ค้างอยู่"""
        self._send("stop")
        self.release()

    def close(self) -> None:
        """ปิดตัวช่วย"""
        self._send("quit")
        self.release()
        with contextlib.suppress(OSError):
            self._process.terminate()


def spawn(binary: pathlib.Path) -> Voice:
    """เปิดตัวช่วยขึ้นมาหนึ่งตัว"""
    process = subprocess.Popen(
        [str(binary)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Voice(process)


def probe(voice: Voice, frames_needed: int = listen.SILENCE_PROBE_FRAMES):
    """ลองอ่านเสียงต้น ๆ คืนสายเสียงพร้อมส่วนที่อ่านไปแล้ว หรือ None ถ้าได้แต่ความเงียบ

    ความเงียบสนิทแปลว่ายูนิตไม่ได้ส่งเสียงจริงมาให้ ซึ่งแยกจากไมค์ปิดไม่ได้เลย
    ไมค์ที่ทำงานอยู่จะมีเสียงพื้นเสมอ
    """
    stream = voice.frames()
    seen = []
    for frame in stream:
        seen.append(frame)
        if len(seen) >= frames_needed:
            break
    if len(seen) < frames_needed or not any(frame.any() for frame in seen):
        return None
    return itertools.chain(seen, stream)


def open_voice() -> tuple[Voice, Iterator] | None:
    """เปิดทางเสียงสองทาง คืน None ถ้าเครื่องนี้ใช้ไม่ได้ ให้ผู้เรียกถอยไปทางปกติ"""
    binary = listen.build_aec()
    if binary is None:
        return None
    voice = spawn(binary)
    if not voice.wait_ready():
        voice.close()
        return None
    stream = probe(voice)
    if stream is None:
        voice.close()
        return None
    return voice, stream
