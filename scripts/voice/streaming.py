"""ตัดข้อความที่ไหลมาทีละชิ้นให้เป็นประโยคที่พูดได้

TTS สังเคราะห์ได้เร็วกว่าที่ LLM เขียนจบ การรอทั้งคำตอบจึงเสียเวลาเปล่า
ตัดเป็นประโยคแล้วทยอยส่งทำให้ได้ยินเสียงแรกเร็วขึ้นมาก
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator

BOUNDARY = re.compile(r"(?<=[.!?…])\s+|\n+")
MIN_CHARS = 28
MAX_CHARS = 220
FIRST_MAX_CHARS = 70
_THAI_BREAK = re.compile(r"(?<=[ก-๙]) (?=[ก-๙])")


def _split_long(chunk: str, limit: int = MAX_CHARS) -> list[str]:
    """ภาษาไทยไม่มีจุดจบประโยค ถ้าชิ้นยาวเกินไปให้ตัดที่ช่องว่างคำไทย"""
    if len(chunk) <= limit:
        return [chunk]
    parts: list[str] = []
    current = chunk
    while len(current) > limit:
        window = current[:limit]
        breaks = list(_THAI_BREAK.finditer(window))
        cut = breaks[-1].start() if breaks else window.rfind(" ")
        if cut <= MIN_CHARS:
            cut = limit
        parts.append(current[:cut].strip())
        current = current[cut:].strip()
        limit = MAX_CHARS
    if current:
        parts.append(current)
    return parts


def sentences(pieces: Iterable[str]) -> Iterator[str]:
    """รวมชิ้นส่วนที่ไหลเข้ามา แล้วคายออกเป็นประโยคที่ยาวพอจะพูด

    ชิ้นแรกถูกตัดสั้นกว่าปกติ เพื่อให้เริ่มได้ยินเสียงเร็วที่สุด
    ชิ้นถัดไปยาวได้เต็มที่เพราะสังเคราะห์ทันขณะที่ชิ้นก่อนหน้ายังเล่นอยู่
    """
    buffer = ""
    limit = FIRST_MAX_CHARS
    for piece in pieces:
        buffer += piece
        while True:
            match = BOUNDARY.search(buffer)
            if not match:
                break
            head, buffer = buffer[:match.start()].strip(), buffer[match.end():]
            if len(head) < MIN_CHARS:
                buffer = f"{head} {buffer}".strip() if head else buffer
                break
            for part in _split_long(head, limit):
                if part:
                    yield part
                    limit = MAX_CHARS
        if len(buffer) > limit:
            parts = _split_long(buffer, limit)
            for part in parts[:-1]:
                if part:
                    yield part
                    limit = MAX_CHARS
            buffer = parts[-1]
    tail = buffer.strip()
    if tail:
        for part in _split_long(tail, limit):
            if part:
                yield part
