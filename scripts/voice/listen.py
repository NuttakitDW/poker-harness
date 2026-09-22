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
from typing import Iterator

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE

SPEECH_THRESHOLD = 0.5
START_FRAMES = 3
END_SILENCE_SECONDS = 0.7
PREROLL_SECONDS = 0.3
MIN_UTTERANCE_SECONDS = 0.4
MAX_UTTERANCE_SECONDS = 30.0

AEC_SOURCE = pathlib.Path(__file__).with_name("capture_aec.swift")
AEC_BINARY = pathlib.Path(__file__).resolve().parents[2] / "tmp" / "bin" / "capture_aec"
AEC_PLIST = pathlib.Path(__file__).with_name("capture_aec.plist")
SILENCE_PROBE_FRAMES = 24

_echo_cancelled = False


@dataclasses.dataclass(frozen=True)
class Utterance:
    """ช่วงเสียงพูดหนึ่งช่วงที่ตัดจากสายเสียงต่อเนื่อง"""

    samples: "object"
    seconds: float


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
        self.reset()
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
        return Utterance(numpy.concatenate(collected), len(collected) * FRAME_SECONDS)


def build_aec() -> pathlib.Path | None:
    """คอมไพล์ตัวจับเสียงที่ตัดเสียงสะท้อน คืน None ถ้าเครื่องคอมไพล์ไม่ได้

    ผลลัพธ์ถูกแคชไว้ และคอมไพล์ใหม่เฉพาะเมื่อซอร์สใหม่กว่าไฟล์ที่มีอยู่
    """
    if not AEC_SOURCE.exists() or not shutil.which("swiftc"):
        return None
    if AEC_BINARY.exists() and AEC_BINARY.stat().st_mtime >= AEC_SOURCE.stat().st_mtime:
        return AEC_BINARY
    AEC_BINARY.parent.mkdir(parents=True, exist_ok=True)

    # ต้องฝัง Info.plist เข้าไปในไบนารี ไม่งั้น macOS จะส่งความเงียบแทนการขอสิทธิ์
    command = ["swiftc", "-O", "-o", str(AEC_BINARY), str(AEC_SOURCE)]
    if AEC_PLIST.exists():
        command += ["-Xlinker", "-sectcreate", "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist", "-Xlinker", str(AEC_PLIST)]
    built = subprocess.run(command, capture_output=True, text=True)
    if built.returncode != 0:
        print(f"คอมไพล์ตัวตัดเสียงสะท้อนไม่สำเร็จ: {built.stderr.strip()[:200]}", file=sys.stderr)
        return None

    # เซ็นแบบ ad-hoc เพื่อให้ระบบจดจำสิทธิ์ที่ผู้ใช้อนุญาตไว้ข้ามการรันแต่ละครั้ง
    signed = subprocess.run(
        ["codesign", "--force", "--sign", "-", str(AEC_BINARY)],
        capture_output=True, text=True)
    if signed.returncode != 0:
        print(f"เซ็นไบนารีไม่สำเร็จ: {signed.stderr.strip()[:200]}", file=sys.stderr)
    return AEC_BINARY


def _aec_frames(binary: pathlib.Path) -> Iterator["object"]:
    """อ่าน PCM float32 จากตัวจับเสียงทีละเฟรม"""
    import numpy

    process = subprocess.Popen([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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

    frames: queue.Queue = queue.Queue()

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


def echo_cancel_active() -> bool:
    """ตัวตัดเสียงสะท้อนกำลังทำงานอยู่หรือไม่ ใช้ตัดสินว่าเปิดให้พูดแทรกได้ไหม"""
    return _echo_cancelled


def frames(device: int | None = None, echo_cancel: bool = True) -> Iterator["object"]:
    """เฟรมเสียงจากไมโครโฟน ใช้ตัวตัดเสียงสะท้อนถ้าใช้การได้จริง

    macOS ไม่แจ้งข้อผิดพลาดเมื่อไม่ได้รับสิทธิ์ไมโครโฟน แต่ส่งความเงียบมาแทน
    จึงต้องลองอ่านจริงก่อนแล้วค่อยตัดสินว่าใช้ทางไหน
    """
    global _echo_cancelled
    _echo_cancelled = False
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


def utterances(device: int | None = None, echo_cancel: bool = True) -> Iterator[Utterance]:
    """คายช่วงเสียงพูดทีละช่วงจากไมโครโฟน จนกว่าจะถูกหยุด"""
    detector = Detector()
    for frame in frames(device=device, echo_cancel=echo_cancel):
        found = detector.push(frame)
        if found:
            yield found
