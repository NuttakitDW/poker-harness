"""ถอดเสียงผ่าน Paxa Labs ทั้งทางสตรีม (คุยสด) และทางไฟล์ (ข้อความเสียงใน Discord)

คู่มือ: https://paxalabs.com/docs/api/stt-live และ https://paxalabs.com/docs/speech-to-text
ทางสตรีมเปิด WebSocket ส่งคำสั่ง start แล้วป้อนเสียง pcm_s16le 16kHz เป็น binary
ฝั่งบริการตัดช่วงพูด (turn) เองเมื่อเงียบ แต่ละ turn ได้ข้อความ final ของตัวเอง
turn สั้นมาก หยุดหายใจกลางประโยคก็ตัดแล้ว จึงต้องรวม turn ที่ตามกันมาติด ๆ เป็นคำถามเดียว

convention "written" ให้ตัวเลขเป็นเลขอารบิก "สิบห้าบิ๊กบลายด์" เป็น 15 ซึ่งตัวอ่านสแตกต้องการ
style "clean" ตัดคำเติมอย่าง เอ่อ อ่า vocabulary ช่วยให้ถอดศัพท์โป๊กเกอร์ติด (สูงสุด 50 คำ)
"""

from __future__ import annotations

import base64
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import NamedTuple

import costs
import keys
import lexicon

LIVE_URL = "wss://api.paxalabs.com/v1/stt/live"
BATCH_URL = "https://api.paxalabs.com/v1/stt"
LIVE_MODEL = "paxa-stt-lite-realtime-v1-preview"
BATCH_MODEL = "paxa-stt-lite-v1-preview"
USER_AGENT = "tamkwai/1.0"
SAMPLE_RATE = 16_000
FULL_SCALE = 32767
LANGUAGE = "th"
CONVENTION = "written"
STYLE = "clean"
CHUNK_SECONDS = 0.12
TIMEOUT_SECONDS = 30.0
MAX_VOCABULARY, MAX_TERM_CHARS = 50, 50
# turn ที่เริ่มภายในเวลานี้หลัง turn ก่อนจบ ถือเป็นประโยคเดียวกัน วัดจากคนพูดคำถามโป๊กเกอร์ยาว ๆ
JOIN_SECONDS = 0.9
# ศัพท์ที่ spot chart ต้องได้ยินให้ถูกมาก่อน ที่เหลือเติมจาก glossary จนครบ 50
PRIORITY_TERMS = ("UTG", "Lojack", "Hijack", "Cutoff", "Button", "Small blind", "Big blind",
                  "All-in", "Shove", "Jam", "Push/fold", "Call", "Fold", "Heads-up", "Ante",
                  "BB ante", "Suited", "Offsuit")


class PaxaError(RuntimeError):
    """ถอดเสียงผ่าน Paxa ไม่สำเร็จ"""


class Result(NamedTuple):
    """ผลถอดเสียงหนึ่งช่วง"""

    text: str
    seconds: float
    audio_seconds: float | None


def load_api_key() -> str:
    return keys.require("PAXA_API")


def vocabulary() -> list[str]:
    """ศัพท์ที่ป้อนให้ช่วยถอด ศัพท์ของ spot chart ก่อน แล้วค่อยเติมจาก glossary"""
    terms = list(dict.fromkeys((*PRIORITY_TERMS, *lexicon.stream_terms())))
    return [term for term in terms if len(term) <= MAX_TERM_CHARS][:MAX_VOCABULARY]


def start_message() -> dict:
    """คำสั่งแรกของสายสตรีม"""
    return {"type": "start", "model": LIVE_MODEL, "language": LANGUAGE,
            "audio": {"encoding": "pcm_s16le", "sample_rate": SAMPLE_RATE},
            "convention": CONVENTION, "style": STYLE, "vocabulary": vocabulary()}


def _record(credits: float, audio_seconds: float, seconds: float, api: str) -> None:
    costs.record(api, costs.paxa_credits_usd(credits), quantity=audio_seconds, seconds=seconds)


class Turns:
    """รวม turn ที่ฝั่งบริการตัดมาเป็นประโยค แยกจากสายเพื่อให้ทดสอบได้โดยไม่ต้องต่อเน็ต

    turn final หนึ่งอันยังไม่ใช่ประโยคจบ ถ้ามีคนพูดต่อภายใน JOIN_SECONDS ก็ต่อท้ายไป
    ประโยคปิดเมื่อเงียบเกินนั้น ผู้เรียกบอกเวลาปัจจุบันผ่าน due() เพื่อให้ทดสอบเวลาได้
    """

    def __init__(self, join_seconds: float = JOIN_SECONDS) -> None:
        self._join = join_seconds
        self._finals: list[str] = []
        self._interim = ""
        self._speaking = False
        self._ended_at: float | None = None

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def partial(self) -> str:
        """ประโยคที่ยังไม่ปิด รวมคำที่ยังไม่ final ใช้แสดงผลเท่านั้น"""
        return " ".join(part for part in (*self._finals, self._interim) if part)

    def push(self, message: dict, now: float) -> None:
        kind = message.get("type")
        if kind == "speech_started":
            self._speaking = True
            self._ended_at = None
        elif kind == "transcript":
            text = str(message.get("text") or "").strip()
            if message.get("is_final"):
                if text:
                    self._finals.append(text)
                self._interim = ""
                self._speaking = False
                self._ended_at = now
            else:
                self._interim = text
                self._speaking = True

    def due(self, now: float) -> str | None:
        """ประโยคที่เงียบนานพอจะปิดแล้ว คืน None ถ้ายังต้องรอ"""
        if self._speaking or self._ended_at is None or now - self._ended_at < self._join:
            return None
        return self.flush()

    def flush(self) -> str | None:
        sentence = " ".join(self._finals).strip()
        self._finals, self._interim, self._ended_at, self._speaking = [], "", None, False
        return sentence or None


def transcribe_pcm(audio: bytes, key: str) -> Result:
    """ป้อนเสียงดิบทั้งช่วงเข้าสายเดียว แล้วรวมข้อความ final ทุก turn"""
    from websockets.sync.client import connect

    started = time.perf_counter()
    finals: list[str] = []
    width = int(SAMPLE_RATE * CHUNK_SECONDS) * 2
    credits = 0.0
    try:
        with connect(LIVE_URL, additional_headers={"Authorization": f"Bearer {key}"},
                     user_agent_header=USER_AGENT, open_timeout=TIMEOUT_SECONDS,
                     ping_interval=None) as socket:
            socket.send(json.dumps(start_message()))
            for offset in range(0, len(audio), width):
                socket.send(audio[offset:offset + width])
            socket.send(json.dumps({"type": "end"}))
            while True:
                message = json.loads(socket.recv(timeout=TIMEOUT_SECONDS))
                kind = message.get("type")
                if kind == "error":
                    raise PaxaError(f"Paxa ตอบ {message.get('code')}")
                if kind == "transcript" and message.get("is_final"):
                    finals.append(str(message.get("text") or "").strip())
                if kind == "done":
                    credits = float(message.get("total_credits") or 0.0)
                    break
    except PaxaError:
        raise
    except Exception as error:
        raise PaxaError(f"สตรีมเสียงเข้า Paxa ไม่สำเร็จ: {error}") from error
    audio_seconds = len(audio) / 2 / SAMPLE_RATE
    elapsed = time.perf_counter() - started
    _record(credits, audio_seconds, elapsed, "paxa-stt-rt")
    return Result(" ".join(part for part in finals if part), elapsed, audio_seconds)


def transcribe_bytes(audio: bytes, key: str, filename: str = "audio.ogg") -> Result:
    """ถอดไฟล์เสียงทั้งไฟล์ทางเดียว รับ mp3 wav flac ogg m4a aac webm ตรง ๆ ไม่ต้องแปลงก่อน"""
    started = time.perf_counter()
    body = json.dumps({"audio": base64.b64encode(audio).decode("ascii"), "model": BATCH_MODEL,
                       "language": LANGUAGE, "convention": CONVENTION, "style": STYLE,
                       "vocabulary": vocabulary()}).encode("utf-8")
    request = urllib.request.Request(BATCH_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS * 2) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise PaxaError(f"Paxa ตอบ {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise PaxaError(f"เรียก Paxa ไม่ได้: {error}") from error
    text = result.get("text")
    if not isinstance(text, str):
        raise PaxaError(f"Paxa ไม่ได้ส่งข้อความกลับมา ({filename})")
    elapsed = time.perf_counter() - started
    audio_seconds = result.get("duration") or result.get("audio_seconds")
    credits = result.get("credits") or result.get("total_credits")
    if credits:
        _record(float(credits), float(audio_seconds or 0.0), elapsed, "paxa-stt")
    return Result(text.strip(), elapsed, float(audio_seconds) if audio_seconds else None)


def transcribe(audio, key: str | None = None, live: bool = True) -> Result:
    """ถอดเสียงจากพาธไฟล์ WAV ทางสตรีม หรือทางไฟล์ถ้า live=False"""
    import wave

    resolved = key or load_api_key()
    path = os.fspath(audio)
    if not live:
        with open(path, "rb") as handle:
            return transcribe_bytes(handle.read(), resolved, os.path.basename(path))
    with wave.open(path) as handle:
        if handle.getframerate() != SAMPLE_RATE or handle.getnchannels() != 1:
            raise PaxaError("ทางสตรีมรับแค่ WAV mono 16kHz")
        return transcribe_pcm(handle.readframes(handle.getnframes()), resolved)


class LiveListener:
    """ฟังไมโครโฟนโดยให้ Paxa ถอดเสียงและตัด turn ใช้แทน soniox_rt.LiveListener ได้ทั้งดุ้น

    สายของ Paxa ปิดเองได้ (เช่นเงียบนาน) จึงต่อใหม่อัตโนมัติ ตอนปิดหูไม่ส่งเสียงเลย
    เพราะ Paxa คิดเงินทุกวินาทีที่ส่งเข้าไป รวมช่วงเงียบ
    """

    RECONNECT_SECONDS = 1.0

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
        self._muted = threading.Event()
        self._echo_cancelled = False
        self._collected: list = []
        self._streamed = 0.0
        self._credits = 0.0
        self._turns = Turns()
        self._lock = threading.Lock()
        self._socket = None
        threading.Thread(target=self._send_audio, daemon=True).start()
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._close_when_quiet, daemon=True).start()

    def _send_audio(self) -> None:
        for frame in self._source:
            if not self._ready.is_set():
                self._echo_cancelled = self._listen.echo_cancel_active()
            if self._muted.is_set():
                continue
            socket = self._socket
            if socket is None:
                continue
            self._collected.append(frame)
            if self._meter is not None:
                self._meter.feed(frame)
            try:
                socket.send((frame * FULL_SCALE).astype("<i2").tobytes())
                self._streamed += len(frame) / SAMPLE_RATE
            except Exception:  # noqa: BLE001 สายหลุดระหว่างส่ง ตัวต่อสายจะเปิดใหม่ให้
                self._socket = None

    def _close_utterance(self, text: str) -> None:
        import numpy

        frames, self._collected = self._collected, []
        seconds = len(frames) * self._listen.FRAME_SECONDS
        samples = numpy.concatenate(frames) if frames else numpy.zeros(0, dtype=numpy.float32)
        self._utterances.put(self._listen.Utterance(
            samples, seconds, closed_at=time.monotonic(), text=text))

    def _close_when_quiet(self) -> None:
        while True:
            time.sleep(0.1)
            with self._lock:
                sentence = self._turns.due(time.monotonic())
            if sentence:
                self._close_utterance(sentence)

    def _run(self) -> None:
        from websockets.sync.client import connect

        while True:
            try:
                with connect(LIVE_URL, additional_headers={"Authorization": f"Bearer {self._key}"},
                             user_agent_header=USER_AGENT, open_timeout=TIMEOUT_SECONDS,
                             ping_interval=None) as socket:
                    socket.send(json.dumps(start_message()))
                    self._socket = socket
                    self._ready.set()
                    for raw in socket:
                        message = json.loads(raw)
                        if message.get("type") == "error":
                            print(f"[ถอดเสียง] Paxa {message.get('code')}", file=sys.stderr)
                            break
                        if message.get("type") == "charged":
                            self._credits += float(message.get("credits") or 0.0)
                        with self._lock:
                            self._turns.push(message, time.monotonic())
                            partial, speaking = self._turns.partial, self._turns.speaking
                        if self._meter is not None:
                            self._meter.hear(partial)
                        if message.get("type") == "done":
                            break
            except Exception as error:  # noqa: BLE001 สายขาดก็ต่อใหม่ ไม่ให้โหมดเสียงตาย
                print(f"[ถอดเสียง] สาย Paxa ขาด: {error}", file=sys.stderr)
            finally:
                self._socket = None
                self._ready.set()
            time.sleep(self.RECONNECT_SECONDS)

    @property
    def streamed_seconds(self) -> float:
        """วินาทีเสียงที่ส่งเข้าสายไปแล้ว Paxa คิดเงินทุกวินาทีนี้ รวมช่วงเงียบ"""
        return self._streamed

    @property
    def credits(self) -> float:
        return self._credits

    def wait_ready(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout)

    @property
    def echo_cancelled(self) -> bool:
        return self._echo_cancelled

    @property
    def speaking(self) -> bool:
        with self._lock:
            return self._turns.speaking

    @property
    def waiting(self) -> int:
        return self._utterances.qsize()

    def take(self, timeout: float | None = None):
        try:
            return self._utterances.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> int:
        dropped = 0
        while True:
            try:
                self._utterances.get_nowait()
            except queue.Empty:
                return dropped
            dropped += 1

    def mute(self) -> None:
        """หยุดส่งเสียงเข้าสาย ไม่เสียเงินช่วงนี้"""
        self._muted.set()
        self.drain()

    def unmute(self) -> None:
        """กลับมาส่งเสียงต่อ โดยไม่เอาเสียงที่ค้างระหว่างปิดหูมาคิด"""
        self._collected = []
        with self._lock:
            self._turns.flush()
        self.drain()
        self._muted.clear()
