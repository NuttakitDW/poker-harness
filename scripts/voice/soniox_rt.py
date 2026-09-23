"""ถอดเสียงผ่าน Soniox ทางสตรีม ซึ่งเป็นทางที่ออกแบบมาสำหรับการคุยสด

ทาง async ของเจ้าเดียวกันต้องอัปโหลดไฟล์ เข้าคิว แล้วถามซ้ำจนเสร็จ กินเวลาหลายสิบวินาที
ทางนี้เปิดสายแล้วป้อนเสียงดิบเข้าไปตรง ๆ ตัวอักษรทยอยกลับมาระหว่างที่ยังพูดอยู่
จึงเร็วพอจะแทนการถอดในเครื่องได้

ศัพท์จาก glossary ถูกส่งเข้าไปเป็น context เหมือนกับที่ป้อนให้ Whisper
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from typing import Iterator, NamedTuple

import costs
import soniox_api

WEBSOCKET_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
MODEL = "stt-rt-v5"
SAMPLE_RATE = soniox_api.SAMPLE_RATE
AUDIO_FORMAT = "pcm_s16le"
CHUNK_SECONDS = 0.12
TIMEOUT_SECONDS = 30.0

# ตัวถอดเสียงคายเครื่องหมายบอกขอบเขตปนมากับคำ ต้องไม่ให้หลุดไปถึงคำตอบ
MARKERS = ("<end>", "<fin>")


class Result(NamedTuple):
    """ผลถอดเสียงหนึ่งช่วงพูด"""

    text: str
    seconds: float
    audio_seconds: float | None


def _config(key: str) -> dict:
    """คำสั่งเปิดสาย ใส่ศัพท์เฉพาะและคำใบ้ภาษาไปพร้อมกัน"""
    return {
        "api_key": key,
        "model": MODEL,
        "audio_format": AUDIO_FORMAT,
        "sample_rate": SAMPLE_RATE,
        "num_channels": 1,
        "language_hints": list(soniox_api.LANGUAGE_HINTS),
        "context": soniox_api.transcription_context(),
        "enable_endpoint_detection": True,
    }


def _chunks(audio: bytes, size: int) -> Iterator[bytes]:
    """ซอยเสียงเป็นชิ้นเท่า ๆ กันตามขนาดที่ฝั่งบริการคาดหวัง"""
    for start in range(0, len(audio), size):
        yield audio[start:start + size]


def clean(text: str) -> str:
    """เอาเครื่องหมายขอบเขตของตัวถอดเสียงออก เหลือแต่ถ้อยคำ"""
    for marker in MARKERS:
        text = text.replace(marker, " ")
    return " ".join(text.split())


def transcribe_pcm(audio: bytes, key: str) -> Result:
    """ป้อนเสียงดิบทั้งช่วงเข้าสายเดียว แล้วรวบตัวอักษรที่ทยอยกลับมา"""
    from websockets.sync.client import connect

    started = time.perf_counter()
    pieces: list[str] = []
    width = int(SAMPLE_RATE * CHUNK_SECONDS) * 2

    try:
        with connect(WEBSOCKET_URL, user_agent_header=soniox_api.USER_AGENT,
                     open_timeout=TIMEOUT_SECONDS, ping_interval=None) as socket:
            socket.send(json.dumps(_config(key)))
            for chunk in _chunks(audio, width):
                socket.send(chunk)
            # สตริงว่างคือสัญญาณว่าเสียงหมดแล้ว ฝั่งบริการจะปิดท้ายคำที่ค้างอยู่ให้
            socket.send("")

            while True:
                message = json.loads(socket.recv(timeout=TIMEOUT_SECONDS))
                if message.get("error_code") is not None:
                    raise soniox_api.SonioxError(
                        f"Soniox ตอบ {message['error_code']}: "
                        f"{message.get('error_message', '')}")
                for token in message.get("tokens", []):
                    if token.get("is_final"):
                        pieces.append(token.get("text", ""))
                if message.get("finished"):
                    break
    except soniox_api.SonioxError:
        raise
    except Exception as error:
        raise soniox_api.SonioxError(f"สตรีมเสียงเข้า Soniox ไม่สำเร็จ: {error}") from error

    audio_seconds = len(audio) / 2 / SAMPLE_RATE
    elapsed = time.perf_counter() - started
    costs.record("soniox-stt-rt", costs.soniox_stt_usd(audio_seconds),
                 quantity=audio_seconds, seconds=elapsed)
    return Result(clean("".join(pieces)), elapsed, audio_seconds)


def transcribe(audio, key: str | None = None) -> Result:
    """ถอดเสียงจากพาธไฟล์ WAV หรือจากตัวอย่างเสียงในหน่วยความจำ"""
    import os
    import wave

    resolved = key or soniox_api.load_api_key()
    if isinstance(audio, (str, os.PathLike)):
        with wave.open(os.fspath(audio)) as handle:
            return transcribe_pcm(handle.readframes(handle.getnframes()), resolved)
    return transcribe_pcm(soniox_api.wav_bytes(audio)[44:], resolved)


class Assembler:
    """ประกอบ token ที่ทยอยเข้ามาเป็นประโยค แยกจากสายเพื่อให้ทดสอบได้โดยไม่ต้องต่อเน็ต

    ฝั่งบริการส่ง <end> มาเมื่อตัดสินว่าผู้พูดหยุดแล้ว นั่นคือขอบเขตประโยค
    ส่วน <fin> บอกว่าไม่มีอะไรตามมาอีก ทั้งคู่เป็นเครื่องหมาย ไม่ใช่คำพูด
    """

    def __init__(self) -> None:
        self._words: list[str] = []
        self._pending = ""
        self._speaking = False

    @property
    def speaking(self) -> bool:
        """มีคำพูดกำลังทยอยเข้ามาอยู่ตอนนี้"""
        return self._speaking

    @property
    def partial(self) -> str:
        """คำของประโยคที่ยังพูดไม่จบ รวมคำที่ฝั่งบริการยังอาจแก้ ใช้แสดงผลเท่านั้น"""
        return clean("".join(self._words) + self._pending)

    def push(self, message: dict) -> list[str]:
        """ป้อนข้อความหนึ่งก้อนจากสาย คืนประโยคที่ปิดแล้วเท่าที่มี"""
        closed: list[str] = []
        # คำที่ยังไม่ final ถูกส่งมาใหม่ทั้งชุดทุกก้อน ชุดเก่าจึงทิ้งได้เลย
        self._pending = ""
        for token in message.get("tokens", []):
            text = token.get("text", "")
            if text == "<end>":
                sentence = clean("".join(self._words))
                self._words = []
                self._pending = ""
                self._speaking = False
                if sentence:
                    closed.append(sentence)
                continue
            if text and text != "<fin>":
                self._speaking = True
            if token.get("is_final"):
                self._words.append(text)
            elif text != "<fin>":
                self._pending += text
        return closed

    def flush(self) -> str:
        """คำที่ค้างอยู่โดยยังไม่เจอขอบเขต ใช้ตอนสายปิดกลางประโยค"""
        sentence = clean("".join(self._words))
        self._words = []
        self._pending = ""
        self._speaking = False
        return sentence


class LiveListener:
    """ฟังไมโครโฟนโดยให้ Soniox เป็นทั้งตัวถอดเสียงและตัวตัดสินว่าพูดจบเมื่อไร

    ใช้แทน listen.Listener ได้ทั้งดุ้น ต่างกันที่ช่วงเสียงที่คายออกมามีคำพูดติดมาแล้ว
    เพราะเสียงถูกถอดไปตั้งแต่ระหว่างที่ยังพูดอยู่ ไม่ต้องรอความเงียบแล้วค่อยถอดทั้งก้อน
    """

    def __init__(self, key: str, device: int | None = None, echo_cancel: bool = False,
                 source=None, meter=None) -> None:
        import listen

        self._key = key
        self._meter = meter
        self._listen = listen
        self._source = source if source is not None else listen.frames(
            device=device, echo_cancel=echo_cancel)
        self._utterances: "queue.Queue" = queue.Queue()
        self._ready = threading.Event()
        self._speaking = threading.Event()
        self._muted = threading.Event()
        self._echo_cancelled = False
        self._collected: list = []
        self._streamed = 0.0
        self._assembler = Assembler()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _send_audio(self, socket) -> None:
        """ส่งเสียงจากไมค์เข้าสายไปเรื่อย ๆ และเก็บสำเนาไว้ให้ผู้เรียกดูระดับเสียง"""
        for frame in self._source:
            if not self._ready.is_set():
                self._echo_cancelled = self._listen.echo_cancel_active()
                self._ready.set()
            if self._muted.is_set():
                continue
            self._collected.append(frame)
            if self._meter is not None:
                self._meter.feed(frame)
            self._streamed += len(frame) / SAMPLE_RATE
            socket.send((frame * soniox_api.FULL_SCALE).astype("<i2").tobytes())

    def _close_utterance(self, text: str) -> None:
        """ปิดช่วงที่พูดจบแล้ว ส่งให้ผู้เรียกพร้อมคำที่ถอดได้"""
        import numpy

        frames, self._collected = self._collected, []
        seconds = len(frames) * self._listen.FRAME_SECONDS
        samples = numpy.concatenate(frames) if frames else numpy.zeros(0, dtype=numpy.float32)
        self._utterances.put(self._listen.Utterance(
            samples, seconds, closed_at=time.monotonic(), text=text))

    def _run(self) -> None:
        from websockets.sync.client import connect

        try:
            with connect(WEBSOCKET_URL, user_agent_header=soniox_api.USER_AGENT,
                         open_timeout=TIMEOUT_SECONDS, ping_interval=None) as socket:
                socket.send(json.dumps(_config(self._key)))
                threading.Thread(target=self._send_audio, args=(socket,), daemon=True).start()
                while True:
                    message = json.loads(socket.recv())
                    if message.get("error_code") is not None:
                        print(f"[ถอดเสียง] {message['error_code']} "
                              f"{message.get('error_message', '')}", file=sys.stderr)
                        return
                    for sentence in self._assembler.push(message):
                        self._close_utterance(sentence)
                    if self._meter is not None:
                        self._meter.hear(self._assembler.partial)
                    if self._assembler.speaking:
                        self._speaking.set()
                    else:
                        self._speaking.clear()
                    if message.get("finished"):
                        return
        except Exception as error:
            print(f"[ถอดเสียง] สายขาด: {error}", file=sys.stderr)
        finally:
            self._ready.set()

    @property
    def streamed_seconds(self) -> float:
        """วินาทีเสียงที่ส่งเข้าสายไปแล้ว ทางสตรีมคิดเงินทุกวินาทีนี้ รวมช่วงที่ไม่มีใครพูด"""
        return self._streamed

    def wait_ready(self, timeout: float | None = None) -> bool:
        """รอจนสายเสียงเริ่มไหล"""
        return self._ready.wait(timeout)

    @property
    def echo_cancelled(self) -> bool:
        """ตัวตัดเสียงสะท้อนทำงานอยู่หรือไม่"""
        return self._echo_cancelled

    @property
    def speaking(self) -> bool:
        """มีคำพูดกำลังทยอยเข้ามาอยู่ตอนนี้"""
        return self._speaking.is_set()

    @property
    def waiting(self) -> int:
        """จำนวนช่วงเสียงที่พูดจบแล้วแต่ยังไม่ได้ตอบ"""
        return self._utterances.qsize()

    def take(self, timeout: float | None = None):
        """เอาช่วงเสียงถัดไป คืน None ถ้าไม่มีภายในเวลาที่รอ"""
        try:
            return self._utterances.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> int:
        """ทิ้งช่วงเสียงที่ค้างอยู่ คืนจำนวนที่ทิ้ง"""
        dropped = 0
        while True:
            try:
                self._utterances.get_nowait()
            except queue.Empty:
                return dropped
            dropped += 1

    def mute(self) -> None:
        """หยุดส่งเสียงเข้าสายชั่วคราว ใช้ตอนเปิดลำโพงโดยไม่มีตัวตัดเสียงสะท้อน"""
        self._muted.set()
        self.drain()

    def unmute(self) -> None:
        """กลับมาส่งเสียงต่อ โดยไม่เอาเสียงที่เกิดระหว่างปิดหูมาคิด"""
        self._collected = []
        self._assembler.flush()
        self.drain()
        self._muted.clear()
