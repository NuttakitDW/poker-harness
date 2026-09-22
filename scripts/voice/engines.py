"""ตัวถอดเสียงหลายเจ้าเบื้องหลังอินเทอร์เฟซเดียว

แต่ละ engine อยู่คนละ virtualenv เพราะชุด dependency ชนกัน
จึง import แบบ lazy และเรียกได้ทีละตัวเท่านั้น
"""

from __future__ import annotations

import time
from typing import Callable, NamedTuple

WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"
TYPHOON_MODEL = "scb10x/typhoon-asr-realtime"


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
    )
    wall = time.perf_counter() - started
    segments = result.get("segments") or []
    audio_seconds = segments[-1].get("end") if segments else None
    return Transcript(str(result.get("text", "")).strip(), wall, audio_seconds)


ENGINES: dict[str, Callable[..., Transcript]] = {
    "typhoon": typhoon,
    "whisper": whisper,
    "whisper-biased": whisper_biased,
}
