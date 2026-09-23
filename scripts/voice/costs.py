"""ตีราคาทุกครั้งที่เรียกบริการที่คิดเงิน แล้วจดลงบันทึกของรอบนั้น

ต้นทุนต่อผู้ใช้ประเมินจากของจริงเท่านั้น จึงต้องรู้ว่าแต่ละรอบใช้ token ตัวอักษร
และวินาทีเสียงไปเท่าไร ราคาทั้งหมดอยู่ที่นี่ที่เดียว เมื่อผู้ให้บริการขึ้นราคาแก้แค่ไฟล์นี้

ราคาตรวจจากหน้าราคาของแต่ละเจ้าเมื่อ PRICES_CHECKED
"""

from __future__ import annotations

import datetime
import threading

import journal

PRICES_CHECKED = "2026-09-23"
# อัตราแลกเปลี่ยนคร่าว ๆ ใช้แปลงราคา Paxa ที่ประกาศเป็นบาท และโชว์ยอดรวมเป็นบาท
THB_PER_USD = 33.0

# DeepSeek ต่อหนึ่งล้าน token ช่วง peak ส่วนนอก peak ลดครึ่ง (deepseek-chat ชี้ไป deepseek-flash)
DEEPSEEK_HIT_PER_M = 0.006
DEEPSEEK_MISS_PER_M = 0.30
DEEPSEEK_OUTPUT_PER_M = 1.20
DEEPSEEK_OFF_PEAK_FACTOR = 0.5
# ช่วง peak เป็นเวลา UTC วันจันทร์ถึงศุกร์ (ไม่นับวันหยุดจีน ซึ่งเราไม่ได้ตาม จึงคิดแพงไว้ก่อน)
DEEPSEEK_PEAK_HOURS = ((1, 4), (6, 10))

# Paxa ขาย 15 เครดิตต่อพันตัวอักษร ราคาหน้าเว็บคิดเป็น 499 บาทต่อล้านตัวอักษร
PAXA_THB_PER_M_CHARS = 499.0

# Soniox คิดตามวินาทีเสียงที่ส่งเข้าไป ทางสตรีมคิดทุกวินาทีที่สายเปิดส่งเสียง รวมช่วงเงียบ
SONIOX_RT_PER_HOUR = 0.12
SONIOX_ASYNC_PER_HOUR = 0.10
SONIOX_TTS_TEXT_PER_M_TOKENS = 4.00
SONIOX_TTS_TOKENS_PER_CHAR = 0.3
SONIOX_TTS_AUDIO_PER_HOUR = 0.70

# ใช้เดา token เมื่อสตรีมถูกตัดก่อนบริการรายงานยอด วัดจากคำถามภาษาไทยจริงสามข้อ
PROMPT_CHARS_PER_TOKEN = 2.9
OUTPUT_CHARS_PER_TOKEN = 2.3
# เสียงไทยที่ความเร็ว 1.15 ราว ๆ นี้ ใช้เดาความยาวเสียงของ Soniox ซึ่งคืน mp3
SPOKEN_CHARS_PER_SECOND = 13.0

_lock = threading.Lock()
_spent: dict[str, float] = {}


def is_peak(moment: datetime.datetime | None = None) -> bool:
    """ตอนนี้อยู่ในช่วงราคาเต็มของ DeepSeek หรือไม่"""
    now = (moment or datetime.datetime.now(datetime.timezone.utc)).astimezone(
        datetime.timezone.utc)
    if now.weekday() >= 5:
        return False
    return any(start <= now.hour < end for start, end in DEEPSEEK_PEAK_HOURS)


def deepseek_usd(hit: int, miss: int, output: int, peak: bool = True) -> float:
    """ราคาหนึ่งคำขอ แยก input ที่โดนแคชออกจากที่ไม่โดน เพราะต่างกันห้าสิบเท่า"""
    usd = (hit * DEEPSEEK_HIT_PER_M + miss * DEEPSEEK_MISS_PER_M
           + output * DEEPSEEK_OUTPUT_PER_M) / 1_000_000
    return usd if peak else usd * DEEPSEEK_OFF_PEAK_FACTOR


def paxa_usd(chars: int) -> float:
    """ราคาสังเคราะห์เสียงของ Paxa ต่อจำนวนตัวอักษรที่ส่งไป"""
    return chars * PAXA_THB_PER_M_CHARS / 1_000_000 / THB_PER_USD


def soniox_tts_usd(chars: int) -> float:
    """ราคาสังเคราะห์เสียงของ Soniox ค่าข้อความบวกค่าเสียงที่เดาจากความยาวข้อความ"""
    text = chars * SONIOX_TTS_TOKENS_PER_CHAR * SONIOX_TTS_TEXT_PER_M_TOKENS / 1_000_000
    audio = chars / SPOKEN_CHARS_PER_SECOND / 3600 * SONIOX_TTS_AUDIO_PER_HOUR
    return text + audio


def soniox_stt_usd(seconds: float, realtime: bool = True) -> float:
    """ราคาถอดเสียงตามวินาทีเสียงที่ส่งไป"""
    rate = SONIOX_RT_PER_HOUR if realtime else SONIOX_ASYNC_PER_HOUR
    return seconds / 3600 * rate


def estimate_tokens(chars: int, per_token: float) -> int:
    """เดาจำนวน token จากจำนวนตัวอักษร ใช้เฉพาะตอนไม่มียอดจริงจากบริการ"""
    return max(0, round(chars / per_token))


def record(api: str, usd: float, **fields) -> None:
    """จดค่าใช้จ่ายหนึ่งครั้งลงบันทึก และบวกเข้ายอดของรอบนี้"""
    with _lock:
        _spent[api] = round(_spent.get(api, 0.0) + usd, 8)
    journal.note("usage", api=api, usd=round(usd, 6), **fields)


def spent() -> dict[str, float]:
    """ยอดใช้จ่ายของรอบนี้แยกตามบริการ คืนสำเนาเพื่อไม่ให้ผู้เรียกแก้ยอดจริงได้"""
    with _lock:
        return dict(_spent)


def summary() -> dict:
    """ยอดรวมสำหรับจดตอนจบรอบ"""
    by_api = {name: round(usd, 6) for name, usd in spent().items()}
    total = sum(by_api.values())
    return {"total_usd": round(total, 6), "total_thb": round(total * THB_PER_USD, 4),
            "by_api": by_api,
            "prices_checked": PRICES_CHECKED}


def reset() -> None:
    """ล้างยอดของรอบก่อน ใช้ตอนเริ่มรอบใหม่และในเทสต์"""
    with _lock:
        _spent.clear()
