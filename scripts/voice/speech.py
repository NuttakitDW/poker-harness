"""เลือกผู้ให้บริการสังเคราะห์เสียง แล้วซ่อนความต่างของแต่ละเจ้าไว้หลังหน้าเดียว

ลูปสนทนาไม่ควรรู้ว่าเสียงมาจากใคร มันต้องการแค่ฟังก์ชันที่รับข้อความแล้วคืนเสียง
และข้อผิดพลาดชนิดเดียวที่จับได้ ไม่ว่าเจ้าไหนจะล้มเหลว

Paxa ไปทาง REST ซึ่งคืนทั้งก้อนในราวสามส่วนสิบวินาที จึงเป็นค่าเริ่มต้น
Soniox ไปทางสตรีมซึ่งช้ากว่าราวห้าวินาทีต่อประโยค ใช้เมื่อไม่เร่ง
"""

from __future__ import annotations

from typing import Callable

import soniox_tts
import speak

PROVIDERS = ("soniox", "paxa")
DEFAULT_PROVIDER = "paxa"

_MODULES = {"soniox": soniox_tts, "paxa": speak}
DEFAULT_VOICES = {
    "soniox": soniox_tts.DEFAULT_VOICE,
    "paxa": speak.DEFAULT_VOICE,
}


class SpeechError(RuntimeError):
    """สังเคราะห์เสียงไม่สำเร็จ ไม่ว่าจะเป็นเจ้าไหน ผู้เรียกจับชนิดเดียวพอ"""


def default_voice(provider: str) -> str:
    """เสียงปริยายของเจ้านั้น ใช้เมื่อผู้เรียกไม่ได้ระบุ"""
    return DEFAULT_VOICES[provider]


def load_api_key(provider: str) -> str:
    """คีย์ของเจ้านั้นจาก environment หรือ .env"""
    return _MODULES[provider].load_api_key()


def synthesizer(provider: str, voice: str | None = None,
                key: str | None = None) -> Callable[[str], tuple[bytes, float]]:
    """คืนฟังก์ชันที่รับข้อความแล้วคืนเสียงกับเวลาที่ใช้

    คีย์ถูกโหลดครั้งเดียวตอนสร้าง ไม่ใช่ทุกประโยค
    """
    if provider not in _MODULES:
        raise SpeechError(f"ไม่รู้จักผู้ให้บริการเสียง {provider}")
    module = _MODULES[provider]
    chosen = voice or default_voice(provider)
    resolved = key or module.load_api_key()
    # Soniox คายเสียงทีละชิ้นระหว่างสังเคราะห์ ซึ่งเร็วกว่าทาง REST ของเจ้าเดียวกันมาก
    call = getattr(module, "stream_synthesize", module.synthesize)

    def speak_text(text: str) -> tuple[bytes, float]:
        try:
            return call(text, chosen, resolved)
        except RuntimeError as error:
            raise SpeechError(str(error)) from error

    return speak_text
