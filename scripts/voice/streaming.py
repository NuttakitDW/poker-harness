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

# สระ วรรณยุกต์ และเครื่องหมายที่ต้องเกาะพยัญชนะตัวหน้า ห้ามตัดแยกออกมา
_TRAILING_MARKS = (
    "\u0e30\u0e31\u0e32\u0e33"
    "\u0e34\u0e35\u0e36\u0e37\u0e38\u0e39\u0e3a"
    "\u0e45\u0e46"
    "\u0e47\u0e48\u0e49\u0e4a\u0e4b\u0e4c\u0e4d\u0e4e"
)
# สระหน้าที่ต้องอยู่กับพยัญชนะตัวถัดไป ห้ามตัดทิ้งไว้ท้ายชิ้น
_LEADING_VOWELS = "\u0e40\u0e41\u0e42\u0e43\u0e44"


def _safe_cut(text: str, cut: int) -> int:
    """ขยับจุดตัดให้ไม่แยกสระหรือวรรณยุกต์ออกจากพยัญชนะที่มันเกาะอยู่"""
    cut = min(max(cut, 1), len(text))
    while cut > 1 and (text[cut] in _TRAILING_MARKS if cut < len(text) else False):
        cut -= 1
    while cut > 1 and text[cut - 1] in _LEADING_VOWELS:
        cut -= 1
    return cut


def _split_long(chunk: str, limit: int = MAX_CHARS) -> list[str]:
    """ภาษาไทยไม่มีจุดจบประโยค ถ้าชิ้นยาวเกินไปให้ตัดที่ช่องว่างคำไทย"""
    if len(chunk) <= limit:
        return [chunk]
    parts: list[str] = []
    current = chunk
    while len(current) > limit:
        window = current[:limit]
        # ช่องว่างระหว่างคำไทยดีที่สุด ถ้าไม่มีหรือชิดต้นเกินไปก็ใช้ช่องว่างไหนก็ได้
        # เคยตัดกลางคำ "ไล่ทุก|บอร์ด" เพราะช่องว่างไทยช่องเดียวอยู่ต้นประโยค ทั้งที่มีช่องว่างหน้า "เป็น" ให้ใช้
        breaks = [match.start() for match in _THAI_BREAK.finditer(window)]
        cut = breaks[-1] if breaks and breaks[-1] > MIN_CHARS else window.rfind(" ")
        if cut <= MIN_CHARS:
            cut = _safe_cut(current, limit)
        parts.append(current[:cut].strip())
        current = current[cut:].strip()
        limit = MAX_CHARS
    if current:
        parts.append(current)
    return parts


def split_reasoning(pieces: Iterable[str], marker: str,
                    opening: str = "") -> Iterator[tuple[str, str]]:
    """แยกช่วงคิดออกจากช่วงพูด คายเป็น (ช่อง, ข้อความ) โดยช่องคือ think หรือ say

    เก็บส่วนคิดไว้ทั้งก้อนก่อนคาย เพราะถ้าคายทีละชิ้นแล้วสุดท้ายไม่เจอตัวคั่น
    จะแยกไม่ออกว่าอันไหนคือคำตอบ และคำตอบจะหายไปจากปากผู้ช่วย
    """
    buffer = ""
    for piece in pieces:
        buffer += piece
        index = buffer.find(marker)
        if index < 0:
            continue
        thought = buffer[:index].strip()
        if opening and thought.startswith(opening):
            thought = thought[len(opening):].strip()
        if thought:
            yield "think", thought
        rest = buffer[index + len(marker):].lstrip()
        if rest:
            yield "say", rest
        for remaining in pieces:
            yield "say", remaining
        return
    # ไม่มีตัวคั่นเลย ถือว่าโมเดลตอบตรง ๆ ทั้งก้อน ดีกว่าเงียบ
    if buffer.strip():
        yield "say", buffer.strip()


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
