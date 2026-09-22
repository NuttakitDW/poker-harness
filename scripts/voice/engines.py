"""ตัวถอดเสียงหลายเจ้าเบื้องหลังอินเทอร์เฟซเดียว

แต่ละ engine อยู่คนละ virtualenv เพราะชุด dependency ชนกัน
จึง import แบบ lazy และเรียกได้ทีละตัวเท่านั้น
"""

from __future__ import annotations

import collections
import os
import re
import time
from typing import Callable, NamedTuple

# ตัวโหลดโมเดลแสดงแถบความคืบหน้าทุกครั้งที่ตรวจแคช ทั้งที่ไม่ได้ดาวน์โหลดอะไร
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"
TYPHOON_MODEL = "scb10x/typhoon-asr-realtime"


_THAI = re.compile(r"[ก-๙]")
# อักษรนอกละตินและนอกไทย เช่นซีริลลิกหรือจีน เป็นร่องรอยว่าเดาภาษาผิด
_OTHER_SCRIPT = re.compile(r"[^\u0000-\u007fก-๙\s]")


REPEAT_WINDOW = 10
MAX_REPEATS = 4


def repetitive(text: str) -> bool:
    """ข้อความวนซ้ำเป็นอาการค้างของตัวถอดเสียง ไม่ใช่คำที่มีคนพูดจริง

    เจอตอนป้อนเสียงรบกวนสั้น ๆ ให้ Whisper แล้วมันวนคำเดิมนับสิบรอบ
    """
    body = text.strip()
    if len(body) < REPEAT_WINDOW * MAX_REPEATS:
        return False
    shingles = collections.Counter(
        body[index:index + REPEAT_WINDOW] for index in range(len(body) - REPEAT_WINDOW))
    return max(shingles.values()) >= MAX_REPEATS


def usable_text(text: str, language: str = "TH") -> bool:
    """ผลถอดเสียงนี้น่าเชื่อพอจะเอาไปตอบไหม

    คลิปสั้นและเบาทำให้ Whisper เดาเป็นภาษาอื่นแล้วคายคำที่ไม่มีใครพูดออกมา
    ถ้าตั้งใจฟังไทยแต่ไม่มีอักษรไทยเลยและมีอักษรของภาษาอื่นโผล่ ถือว่าเดาผิด
    """
    body = text.strip()
    if not body or repetitive(body):
        return False
    if language.upper() != "TH":
        return True
    if _THAI.search(body):
        return True
    return not _OTHER_SCRIPT.search(body)


class Transcript(NamedTuple):
    """ผลถอดเสียงหนึ่งไฟล์"""

    text: str
    seconds: float
    audio_seconds: float | None


def _hypothesis_text(value: object) -> str:
    """NeMo คืน Hypothesis ไม่ใช่ str จึงต้องดึง .text ออกมาก่อน"""
    return str(getattr(value, "text", value)).strip()


def typhoon(path: str, device: str = "auto", language: str | None = None) -> Transcript:
    """Typhoon ASR Real-time (FastConformer-Transducer) เฉพาะภาษาไทย"""
    from typhoon_asr import transcribe

    started = time.perf_counter()
    result = transcribe(path, model_name=TYPHOON_MODEL, device=device)
    wall = time.perf_counter() - started
    if not isinstance(result, dict):
        return Transcript(_hypothesis_text(result), wall, None)
    return Transcript(
        _hypothesis_text(result.get("text", "")),
        float(result.get("processing_time") or wall),
        result.get("audio_duration"),
    )


def whisper(path: str, device: str = "auto", language: str | None = "th") -> Transcript:
    """Whisper large-v3-turbo ผ่าน MLX รันบน Apple Silicon"""
    import mlx_whisper

    started = time.perf_counter()
    result = mlx_whisper.transcribe(path, path_or_hf_repo=WHISPER_REPO, language=language)
    wall = time.perf_counter() - started
    segments = result.get("segments") or []
    audio_seconds = segments[-1].get("end") if segments else None
    return Transcript(str(result.get("text", "")).strip(), wall, audio_seconds)


def whisper_biased(path: str, device: str = "auto", language: str | None = "th") -> Transcript:
    """Whisper เดิม แต่ป้อนศัพท์จาก glossary เข้า initial_prompt เพื่อเอียงคำ"""
    import mlx_whisper

    from lexicon import bias_prompt

    started = time.perf_counter()
    result = mlx_whisper.transcribe(
        path,
        path_or_hf_repo=WHISPER_REPO,
        language=language,
        initial_prompt=bias_prompt() or None,
        condition_on_previous_text=False,
        # ถอดรอบเดียว ไม่ไล่หลายอุณหภูมิ ไม่งั้นคลิปที่ถอดไม่ออกกินเวลาเป็นสิบวินาที
        temperature=0.0,
    )
    wall = time.perf_counter() - started
    segments = result.get("segments") or []
    audio_seconds = segments[-1].get("end") if segments else None
    return Transcript(str(result.get("text", "")).strip(), wall, audio_seconds)


def soniox(path, device: str = "auto", language: str | None = "th") -> Transcript:
    """Soniox บนคลาวด์ รับศัพท์จาก glossary เป็นรายการแทนการยัดใส่ประโยคชี้นำ"""
    import soniox_api

    result = soniox_api.transcribe(path)
    return Transcript(result.text, result.seconds, result.audio_seconds)


def soniox_realtime(path, device: str = "auto", language: str | None = "th") -> Transcript:
    """Soniox ทางสตรีม ซึ่งเป็นทางที่เร็วพอจะใช้คุยสด ต่างจากทาง async ที่ต้องเข้าคิว"""
    import soniox_rt

    result = soniox_rt.transcribe(path)
    return Transcript(result.text, result.seconds, result.audio_seconds)


ENGINES: dict[str, Callable[..., Transcript]] = {
    "typhoon": typhoon,
    "whisper": whisper,
    "whisper-biased": whisper_biased,
    "soniox": soniox,
    "soniox-rt": soniox_realtime,
}
