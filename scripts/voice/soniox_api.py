"""ถอดเสียงผ่าน Soniox Speech-to-Text บนคลาวด์

Whisper ที่รันในเครื่องถอดทั้งคลิปหลังผู้พูดจบ และรับคำชี้นำได้แค่ประโยคสั้น ๆ
Soniox รับศัพท์เฉพาะเข้ามาเป็นรายการตรง ๆ และสลับไทยอังกฤษกลางประโยคได้เอง
โมดูลนี้คือทาง async สำหรับวัดคุณภาพในสนามเดียวกับ engine อื่นก่อนตัดสินใจ
ว่าจะย้ายสายเสียงหลักไปทางคลาวด์หรือไม่ ทางสตรีมอยู่คนละโมดูล

ใช้เวลาไป-กลับหลายรอบต่อหนึ่งคลิป จึงไม่เหมาะกับการคุยสดเท่าทางสตรีม
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import wave
from typing import NamedTuple

import costs
import keys
import lexicon

BASE_URL = "https://api.soniox.com/v1"
# ด่านหน้าของ Soniox ปฏิเสธ User-Agent ปริยายของ urllib ด้วย 403 ต้องบอกชื่อตัวเองไป
USER_AGENT = "tamkwai/1.0"
MODEL = "stt-async-v5"
LANGUAGE_HINTS = ("th", "en")
DOMAIN = "Poker strategy"
TOPIC = "คำถามภาษาไทยเรื่องกลยุทธ์โป๊กเกอร์ที่แทรกศัพท์อังกฤษ"

SAMPLE_RATE = 16_000
FULL_SCALE = 32767

RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.6
TIMEOUT_SECONDS = 60
POLL_SECONDS = 0.25
POLL_TIMEOUT_SECONDS = 180.0


class SonioxError(RuntimeError):
    """ถอดเสียงผ่าน Soniox ไม่สำเร็จ ผู้เรียกตัดสินเองว่าจะถอยไปใช้ engine อื่นไหม"""


class Result(NamedTuple):
    """ผลถอดเสียงหนึ่งคลิป เวลาเป็นเวลารวมทั้งการอัปโหลดและการรอคิว"""

    text: str
    seconds: float
    audio_seconds: float | None


def load_api_key() -> str:
    """คีย์ Soniox จาก environment หรือ .env"""
    return keys.require("SONIOX_API", "SONIOX_API_KEY")


# ศัพท์ของ spot chart ที่ต้องได้เป็นตัวสะกดอังกฤษ ไม่ใช่คำไทยตามเสียงอย่าง บัตท่อน สมอลไบล์
SPOT_TERMS = (
    "UTG", "UTG+1", "Lojack", "Hijack", "Cutoff", "Button", "Small blind", "Big blind",
    "BB", "SB", "all-in", "jam", "shove", "call", "fold", "push/fold", "heads-up", "6-max",
    "BB ante", "ante", "AoF", "All-in or Fold", "offsuit", "suited", "Ace", "King", "Queen", "Jack", "Ten",
)
# ตัวอย่างประโยคถาม spot ที่เขียนแบบที่ตัวอ่าน regex อ่านออก ให้ตัวถอดเสียงเห็นรูปแบบที่ต้องการ
SPOT_TEXT = ("Thai poker players ask push/fold questions mixing Thai and English. "
             "Write seat names, actions and cards in English and numbers as digits, e.g. "
             "Button all-in 10 big blinds, Small blind call ด้วยอะไร; "
             "Cutoff jam 15 big blinds เราอยู่ Big blind; "
             "UTG all-in แล้ว Button call เราอยู่ Small blind 5 big blinds; "
             "ถือ Jack 2 offsuit; ถือ Ace King suited; heads-up; BB ante; AoF Big blind เจอ Cutoff.")


def _base_context() -> dict:
    return {
        "general": [
            {"key": "domain", "value": DOMAIN},
            {"key": "topic", "value": TOPIC},
        ],
        "terms": list(lexicon.stream_terms()),
    }


def _spot_context() -> dict:
    """ศัพท์ spot chart ขึ้นก่อน ตามด้วย glossary เดิม และประโยคตัวอย่าง"""
    base = _base_context()
    terms = list(dict.fromkeys((*SPOT_TERMS, *base["terms"])))
    return {**base, "terms": terms, "text": SPOT_TEXT}


# general คือ glossary ใช้กับลูกชุบที่ถามได้ทุกเรื่อง spot ใช้กับ make chart และบอท Discord เท่านั้น
# วัด 2026-09-25: บนคำถาม spot 15 ข้อ (scripts/voice/spot_audio_eval.py) spot อ่านถูกทั้งข้อ
# 13% -> 40-47% แต่บนคำถามทั่วไป 10 ข้อ spot ทำให้ CER 0.047 -> 0.108 เพราะดึงศัพท์ทั่วไปอย่าง
# Buy-in ให้กลายเป็นคำไทย จึงแยกใช้ตามงาน ไม่ใช้ spot กับทุกงาน
CONTEXTS = {
    "general": _base_context,
    "spot-terms": lambda: {**_base_context(),
                           "terms": list(dict.fromkeys((*SPOT_TERMS, *lexicon.stream_terms())))},
    "spot": _spot_context,
}


def transcription_context(kind: str = "general") -> dict:
    """บอกโมเดลว่ากำลังฟังเรื่องอะไรและคาดว่าจะเจอศัพท์ตัวไหน kind คือ general หรือ spot"""
    if kind not in CONTEXTS:
        raise ValueError(f"ไม่มี context {kind!r} เลือกได้ {sorted(CONTEXTS)}")
    return CONTEXTS[kind]()


def wav_bytes(samples) -> bytes:
    """แปลงตัวอย่างเสียง float32 ในหน่วยความจำเป็นไฟล์ WAV สำหรับอัปโหลด

    ค่าที่เกินช่วงถูกตรึงไว้ที่ขอบ ไม่ปล่อยให้ล้นกลับเป็นคลื่นคนละรูป
    """
    import numpy

    clipped = numpy.clip(numpy.asarray(samples, dtype=numpy.float32), -1.0, 1.0)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((clipped * FULL_SCALE).astype("<i2").tobytes())
    return buffer.getvalue()


def _multipart(filename: str, payload: bytes) -> tuple[bytes, str]:
    """ประกอบ body แบบ multipart เองเพื่อไม่ต้องพึ่ง dependency เพิ่ม"""
    boundary = uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + payload + tail, f"multipart/form-data; boundary={boundary}"


def _call(method: str, path: str, key: str, *, payload: dict | None = None,
          body: bytes | None = None, content_type: str | None = None) -> dict:
    """เรียก API หนึ่งครั้ง ลองซ้ำเฉพาะความผิดพลาดที่มีโอกาสหายเอง"""
    data = body if body is not None else (
        json.dumps(payload).encode("utf-8") if payload is not None else None)
    headers = {"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    if content_type:
        headers["Content-Type"] = content_type
    elif payload is not None:
        headers["Content-Type"] = "application/json"

    last = ""
    for attempt in range(RETRIES):
        request = urllib.request.Request(
            f"{BASE_URL}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:200]
            last = f"Soniox ตอบ {error.code}: {detail}"
            # คีย์ผิดหรือคำขอผิดรูป ลองอีกกี่ครั้งก็ได้คำตอบเดิม
            if error.code < 500 and error.code != 429:
                break
        except (urllib.error.URLError, OSError) as error:
            last = f"เรียก Soniox ไม่สำเร็จ: {error}"
        if attempt < RETRIES - 1:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise SonioxError(last or "เรียก Soniox ไม่สำเร็จ")


def _await_transcript(job: str, key: str) -> dict:
    """รอจนงานถอดเสียงเสร็จ คืนสถานะสุดท้าย"""
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        status = _call("GET", f"/transcriptions/{job}", key)
        state = status.get("status")
        if state == "completed":
            return status
        if state == "error":
            raise SonioxError(status.get("error_message") or "Soniox ถอดเสียงไม่สำเร็จ")
        if time.monotonic() > deadline:
            raise SonioxError(f"รอผลถอดเสียงเกิน {POLL_TIMEOUT_SECONDS:.0f} วินาที")
        time.sleep(POLL_SECONDS)


def _discard(path: str, key: str) -> None:
    """ลบของที่ฝากไว้บนคลาวด์ ความล้มเหลวตรงนี้ไม่ควรทำให้คำตอบที่ได้มาแล้วหาย"""
    try:
        _call("DELETE", path, key)
    except SonioxError:
        pass


def transcribe_bytes(audio: bytes, key: str, filename: str = "utterance.wav",
                     context: str = "general") -> Result:
    """อัปโหลดเสียงหนึ่งคลิป ถอดเสียง แล้วเก็บกวาดไฟล์กับงานที่ฝากไว้"""
    started = time.perf_counter()
    body, content_type = _multipart(filename, audio)
    file_id = _call("POST", "/files", key, body=body, content_type=content_type).get("id")
    if not file_id:
        raise SonioxError("อัปโหลดไฟล์แล้วไม่ได้รหัสไฟล์กลับมา")

    job = ""
    try:
        job = _call("POST", "/transcriptions", key, payload={
            "model": MODEL,
            "file_id": file_id,
            "language_hints": list(LANGUAGE_HINTS),
            "context": transcription_context(context),
        }).get("id", "")
        if not job:
            raise SonioxError("สั่งถอดเสียงแล้วไม่ได้รหัสงานกลับมา")
        status = _await_transcript(job, key)
        transcript = _call("GET", f"/transcriptions/{job}/transcript", key)
    finally:
        if job:
            _discard(f"/transcriptions/{job}", key)
        _discard(f"/files/{file_id}", key)

    text = "".join(token.get("text", "") for token in transcript.get("tokens", []))
    milliseconds = status.get("audio_duration_ms")
    if milliseconds:
        costs.record("soniox-stt-async", costs.soniox_stt_usd(milliseconds / 1000, realtime=False),
                     quantity=milliseconds / 1000, seconds=time.perf_counter() - started)
    return Result(text.strip(), time.perf_counter() - started,
                  milliseconds / 1000 if milliseconds else None)


def transcribe(audio, key: str | None = None) -> Result:
    """ถอดเสียงจากพาธไฟล์ หรือจากตัวอย่างเสียงในหน่วยความจำ"""
    resolved = key or load_api_key()
    if isinstance(audio, (str, os.PathLike)):
        path = os.fspath(audio)
        with open(path, "rb") as handle:
            return transcribe_bytes(handle.read(), resolved, os.path.basename(path))
    return transcribe_bytes(wav_bytes(audio), resolved)
