"""ฟังไมโครโฟนต่อเนื่องแล้วตัดออกเป็นช่วงที่มีคนพูด

ใช้ Silero VAD ตัดสินว่าเฟรมไหนมีเสียงพูด แล้วรอความเงียบช่วงหนึ่ง
จึงถือว่าผู้พูดจบประโยค การรอความเงียบคือตัวกำหนด latency ที่ผู้ใช้รู้สึกได้
สั้นไปจะตัดกลางประโยค ยาวไปจะรู้สึกว่าระบบอืด
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Iterator

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE

SPEECH_THRESHOLD = 0.5
START_FRAMES = 3
END_SILENCE_SECONDS = 0.9
PREROLL_SECONDS = 0.3
MIN_UTTERANCE_SECONDS = 0.4
MAX_UTTERANCE_SECONDS = 45.0

AEC_SOURCE = pathlib.Path(__file__).with_name("capture_aec.swift")
AEC_BUNDLE = pathlib.Path(__file__).resolve().parents[2] / "tmp" / "bin" / "PokerHarnessVoice.app"
AEC_BINARY = AEC_BUNDLE / "Contents" / "MacOS" / "PokerHarnessVoice"
AEC_PLIST = pathlib.Path(__file__).with_name("capture_aec.plist")
SILENCE_PROBE_FRAMES = 24

_echo_cancelled = False
_pending: "queue.Queue | None" = None


@dataclasses.dataclass(frozen=True)
class Utterance:
    """ช่วงเสียงพูดหนึ่งช่วงที่ตัดจากสายเสียงต่อเนื่อง"""

    samples: "object"
    seconds: float
    closed_at: float = 0.0
    silence_before: float = 0.0
    cut_short: bool = False
    # ตัวฟังที่ถอดเสียงให้เสร็จมาในตัวจะใส่คำพูดมาด้วย ผู้เรียกจึงไม่ต้องถอดซ้ำ
    text: str | None = None


class Endpointer:
    """ตรรกะตัดสินขอบเขตประโยค แยกจากโมเดลเพื่อให้ทดสอบได้โดยไม่ต้องมีไมค์

    รับเพียงว่าเฟรมนั้นมีเสียงพูดหรือไม่ แล้วบอกว่าควรปิดประโยคเมื่อใด
    """

    def __init__(self, start_frames: int = START_FRAMES) -> None:
        self.start_frames = start_frames
        self._preroll: collections.deque = collections.deque(
            maxlen=max(1, int(PREROLL_SECONDS / FRAME_SECONDS)))
        self._collected: list = []
        self._speech_run = 0
        self._silence_seconds = 0.0
        self._speaking = False
        self.cut_short = False

    def reset(self) -> None:
        """ล้างสถานะ ใช้หลังจบประโยคหรือเมื่อเริ่มฟังรอบใหม่"""
        self._preroll.clear()
        self._collected = []
        self._speech_run = 0
        self._silence_seconds = 0.0
        self._speaking = False

    @property
    def speaking(self) -> bool:
        """กำลังมีคนพูดอยู่หรือไม่"""
        return self._speaking

    @property
    def seconds(self) -> float:
        """ความยาวเสียงที่สะสมไว้แล้ว"""
        return len(self._collected) * FRAME_SECONDS

    def push(self, frame, is_speech: bool) -> list | None:
        """ป้อนเฟรมหนึ่งเฟรม คืนรายการเฟรมทั้งประโยคเมื่อตัดสินว่าพูดจบ"""
        if not self._speaking:
            self._preroll.append(frame)
            self._speech_run = self._speech_run + 1 if is_speech else 0
            if self._speech_run < self.start_frames:
                return None
            self._speaking = True
            self._collected = list(self._preroll)
            self._preroll.clear()
            self._silence_seconds = 0.0
            return None

        self._collected.append(frame)
        self._silence_seconds = 0.0 if is_speech else self._silence_seconds + FRAME_SECONDS
        length = self.seconds

        if self._silence_seconds < END_SILENCE_SECONDS and length < MAX_UTTERANCE_SECONDS:
            return None

        collected = self._collected
        trailing_silence = self._silence_seconds
        # ชนเพดานความยาวโดยยังไม่เงียบ แปลว่าคนพูดยังไม่จบ ผู้เรียกควรรอท่อนต่อไป
        cut_short = trailing_silence < END_SILENCE_SECONDS
        self.reset()
        self.cut_short = cut_short
        if length - trailing_silence < MIN_UTTERANCE_SECONDS:
            return None
        return collected


class Detector:
    """รวม Silero VAD เข้ากับตรรกะตัดสินขอบเขตประโยค"""

    def __init__(self, start_frames: int = START_FRAMES) -> None:
        from silero_vad import load_silero_vad

        self._model = load_silero_vad()
        self._endpointer = Endpointer(start_frames)

    def reset(self) -> None:
        """ล้างสถานะทั้งของโมเดลและของตัวตัดสิน"""
        self._model.reset_states()
        self._endpointer.reset()

    @property
    def speaking(self) -> bool:
        """กำลังมีคนพูดอยู่หรือไม่ ใช้ตัดสินใจพูดแทรก"""
        return self._endpointer.speaking

    def _probability(self, frame) -> float:
        import torch

        with torch.no_grad():
            return float(self._model(torch.from_numpy(frame), SAMPLE_RATE).item())

    def push(self, frame) -> Utterance | None:
        """ป้อนเฟรมหนึ่งเฟรม คืนช่วงเสียงเมื่อตัดสินว่าผู้พูดจบประโยคแล้ว"""
        import numpy

        collected = self._endpointer.push(frame, self._probability(frame) >= SPEECH_THRESHOLD)
        if collected is None:
            return None
        self._model.reset_states()
        return Utterance(numpy.concatenate(collected), len(collected) * FRAME_SECONDS,
                         cut_short=self._endpointer.cut_short)


def build_aec() -> pathlib.Path | None:
    """คอมไพล์ตัวจับเสียงที่ตัดเสียงสะท้อน คืน None ถ้าเครื่องคอมไพล์ไม่ได้

    ผลลัพธ์ถูกแคชไว้ และคอมไพล์ใหม่เฉพาะเมื่อซอร์สใหม่กว่าไฟล์ที่มีอยู่
    """
    if not AEC_SOURCE.exists() or not shutil.which("swiftc"):
        return None
    if AEC_BINARY.exists() and AEC_BINARY.stat().st_mtime >= AEC_SOURCE.stat().st_mtime:
        return AEC_BINARY
    # ต้องเป็น .app จริง ไม่ใช่ไฟล์ executable เปล่า ไม่งั้นระบบไม่ถามขอสิทธิ์ไมโครโฟน
    # แต่ส่งความเงียบมาให้แทน ซึ่งแยกจากกรณีไมค์ปิดไม่ได้เลย
    AEC_BINARY.parent.mkdir(parents=True, exist_ok=True)
    if AEC_PLIST.exists():
        shutil.copyfile(AEC_PLIST, AEC_BUNDLE / "Contents" / "Info.plist")

    built = subprocess.run(
        ["swiftc", "-O", "-o", str(AEC_BINARY), str(AEC_SOURCE)],
        capture_output=True, text=True)
    if built.returncode != 0:
        print(f"คอมไพล์ตัวตัดเสียงสะท้อนไม่สำเร็จ: {built.stderr.strip()[:200]}", file=sys.stderr)
        return None

    # เซ็นทั้ง bundle เพื่อให้ระบบจดจำสิทธิ์ที่อนุญาตไว้ข้ามการรันแต่ละครั้ง
    signed = subprocess.run(
        ["codesign", "--force", "--sign", "-", str(AEC_BUNDLE)],
        capture_output=True, text=True)
    if signed.returncode != 0:
        print(f"เซ็น bundle ไม่สำเร็จ: {signed.stderr.strip()[:200]}", file=sys.stderr)
    return AEC_BINARY


def _aec_frames(binary: pathlib.Path) -> Iterator["object"]:
    """อ่าน PCM float32 จากตัวจับเสียงทีละเฟรม"""
    import numpy

    # ต้องคา stdin ไว้ ตัวช่วยถือว่า stdin ปิดคือสัญญาณให้เลิกทำงาน
    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def drain_errors() -> None:
        for line in process.stderr:
            message = line.decode("utf-8", "replace").strip()
            if message and message != "ready":
                print(f"[เสียงเข้า] {message}", file=sys.stderr)

    threading.Thread(target=drain_errors, daemon=True).start()
    width = FRAME_SAMPLES * 4
    try:
        while True:
            chunk = process.stdout.read(width)
            if not chunk or len(chunk) < width:
                return
            yield numpy.frombuffer(chunk, dtype=numpy.float32).copy()
    finally:
        process.terminate()


def _portaudio_frames(device: int | None) -> Iterator["object"]:
    """อ่านเฟรมจากไมโครโฟนตรง ๆ โดยไม่ตัดเสียงสะท้อน"""
    import numpy
    import sounddevice

    global _pending
    frames: queue.Queue = queue.Queue()
    _pending = frames

    def capture(indata, _frames, _time, status) -> None:
        if status:
            print(f"เสียงเข้าไม่ปกติ: {status}", file=sys.stderr)
        frames.put(indata[:, 0].copy().astype(numpy.float32))

    with sounddevice.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SAMPLES,
        channels=1,
        dtype="float32",
        device=device,
        callback=capture,
    ):
        while True:
            yield frames.get()


def backlog_seconds() -> float:
    """เสียงที่ค้างในคิวรอให้อ่าน บอกว่าลูปหลักตามเสียงจริงไม่ทันแค่ไหน"""
    return _pending.qsize() * FRAME_SECONDS if _pending is not None else 0.0


def echo_cancel_active() -> bool:
    """ตัวตัดเสียงสะท้อนกำลังทำงานอยู่หรือไม่ ใช้ตัดสินว่าเปิดให้พูดแทรกได้ไหม"""
    return _echo_cancelled


def frames(device: int | None = None, echo_cancel: bool = False) -> Iterator["object"]:
    """เฟรมเสียงจากไมโครโฟน ทางเดียวไม่มีการเล่นเสียงกลับ

    ทางนี้ใช้สำหรับเครื่องมือที่ฟังเฉย ๆ เช่นตรวจไมค์ ถ้าต้องการตัดเสียงสะท้อน
    ตอนคุยโต้ตอบให้ใช้ duplex.open_voice แทน เพราะยูนิตต้องเป็นตัวเล่นเสียงเองด้วย
    จึงจะรู้ว่าต้องลบคลื่นอะไรออกจากไมค์
    """
    global _echo_cancelled, _pending
    _echo_cancelled = False
    _pending = None
    binary = build_aec() if echo_cancel and device is None else None
    if binary:
        stream = _aec_frames(binary)
        probe = []
        for frame in stream:
            probe.append(frame)
            if len(probe) >= SILENCE_PROBE_FRAMES:
                break
        if any(frame.any() for frame in probe):
            _echo_cancelled = True
            yield from probe
            yield from stream
            return
        stream.close()
    yield from _portaudio_frames(device)


def utterances(device: int | None = None, echo_cancel: bool = False) -> Iterator[Utterance]:
    """คายช่วงเสียงพูดทีละช่วงจากไมโครโฟน จนกว่าจะถูกหยุด"""
    detector = Detector()
    for frame in frames(device=device, echo_cancel=echo_cancel):
        found = detector.push(frame)
        if found:
            yield found


class Listener:
    """ฟังไมโครโฟนในเธรดของตัวเอง แล้วส่งช่วงเสียงที่พูดจบออกมาทางคิว

    ต้องแยกเธรด เพราะการถอดเสียงและการตอบใช้เวลาหลายวินาที ถ้าอ่านไมค์
    ในลูปเดียวกับการตอบ เฟรมจะกองในคิวแล้วถูกอ่านย้อนหลัง ระบบจะไปตอบเสียง
    ที่ผ่านไปนานแล้วและตามหลังผู้พูดมากขึ้นเรื่อย ๆ
    """

    def __init__(self, device: int | None = None, echo_cancel: bool = False,
                 source: Iterator["object"] | None = None, meter=None) -> None:
        self._device = device
        self._meter = meter
        self._echo_cancel = echo_cancel
        self._source = source
        self._utterances: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._speaking = threading.Event()
        self._muted = threading.Event()
        self._echo_cancelled = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        detector = Detector()
        since_last = 0
        stream = self._source if self._source is not None else frames(
            device=self._device, echo_cancel=self._echo_cancel)
        for frame in stream:
            if not self._ready.is_set():
                self._echo_cancelled = echo_cancel_active()
                self._ready.set()
            if self._muted.is_set():
                self._speaking.clear()
                detector.reset()
                since_last = 0
                continue

            since_last += 1
            if self._meter is not None:
                self._meter.feed(frame)
            found = detector.push(frame)
            if detector.speaking:
                self._speaking.set()
            else:
                self._speaking.clear()
            if not found:
                continue
            quiet = max(0.0, since_last * FRAME_SECONDS - found.seconds)
            since_last = 0
            self._utterances.put(dataclasses.replace(
                found, closed_at=time.monotonic(), silence_before=quiet))

    def wait_ready(self, timeout: float | None = None) -> bool:
        """รอจนสายเสียงเริ่มไหล คืนว่าเริ่มทันในเวลาที่รอหรือไม่"""
        return self._ready.wait(timeout)

    @property
    def echo_cancelled(self) -> bool:
        """ตัวตัดเสียงสะท้อนทำงานอยู่หรือไม่ ใช้ตัดสินว่าเปิดให้พูดแทรกได้ไหม"""
        return self._echo_cancelled

    @property
    def speaking(self) -> bool:
        """มีคนกำลังพูดอยู่ตอนนี้ ใช้รู้ตัวว่าถูกแทรกก่อนที่ประโยคจะจบ"""
        return self._speaking.is_set()

    @property
    def waiting(self) -> int:
        """จำนวนช่วงเสียงที่พูดจบแล้วแต่ยังไม่ได้ตอบ"""
        return self._utterances.qsize()

    def take(self, timeout: float | None = None) -> Utterance | None:
        """เอาช่วงเสียงถัดไป คืน None ถ้าไม่มีภายในเวลาที่รอ"""
        try:
            return self._utterances.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> int:
        """ทิ้งช่วงเสียงที่ค้างอยู่ คืนจำนวนที่ทิ้ง ใช้ตอนไม่ต้องการตอบเสียงเก่า"""
        dropped = 0
        while True:
            try:
                self._utterances.get_nowait()
            except queue.Empty:
                return dropped
            dropped += 1

    def mute(self) -> None:
        """หยุดฟังชั่วคราว ใช้ตอนเปิดลำโพงเพื่อไม่ให้ได้ยินเสียงตัวเอง"""
        self._muted.set()
        self.drain()

    def unmute(self) -> None:
        """กลับมาฟังต่อ โดยไม่เอาเสียงที่เกิดระหว่างปิดหูมาคิด"""
        self.drain()
        self._muted.clear()
