"""แปลงคำบอกจำนวนภาษาไทยเป็นตัวเลข เพื่อให้เทียบผล STT ได้อย่างเป็นธรรม

STT บางตัวเขียน "25%" บางตัวเขียน "ยี่สิบห้าเปอร์เซ็นต์" ทั้งสองแบบถูกต้อง
การวัด CER โดยไม่ทำให้เป็นรูปเดียวกันก่อนจะลงโทษตัวที่เขียนเป็นตัวเลขอย่างไม่ยุติธรรม
"""

from __future__ import annotations

import re

DIGITS = {
    "ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3,
    "สี่": 4, "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9,
}
SCALES = {"สิบ": 10, "ร้อย": 100, "พัน": 1000, "หมื่น": 10_000, "แสน": 100_000}
MILLION = "ล้าน"
POINT = "จุด"

_VOCAB = tuple(sorted([*DIGITS, *SCALES, MILLION, POINT], key=len, reverse=True))
_PERCENT_WORDS = ("เปอร์เซ็นต์", "เปอร์เซนต์", "เปอเซ็นต์")


def _tokenize(text: str, start: int) -> tuple[list[str], int]:
    """เก็บคำบอกจำนวนที่ต่อกันตั้งแต่ตำแหน่ง start แบบจับคำยาวก่อน"""
    tokens: list[str] = []
    index = start
    while index < len(text):
        for word in _VOCAB:
            if text.startswith(word, index):
                tokens.append(word)
                index += len(word)
                break
        else:
            break
    return tokens, index


def _combine(tokens: list[str]) -> int:
    """รวมคำบอกจำนวนเป็นจำนวนเต็มตามหลักการอ่านเลขไทย"""
    total = 0
    current = 0
    for token in tokens:
        if token in DIGITS:
            current = DIGITS[token]
        elif token in SCALES:
            current = current or 1
            total += current * SCALES[token]
            current = 0
        elif token == MILLION:
            total = (total + (current or 1)) * 1_000_000
            current = 0
    return total + current


def _render(tokens: list[str]) -> str:
    """แปลงกลุ่มคำเป็นข้อความตัวเลข รองรับทศนิยมที่คั่นด้วย 'จุด'"""
    if POINT not in tokens:
        return str(_combine(tokens))
    split = tokens.index(POINT)
    whole, fraction = tokens[:split], tokens[split + 1:]
    if not fraction or any(t not in DIGITS for t in fraction):
        return str(_combine(tokens))
    decimals = "".join(str(DIGITS[t]) for t in fraction)
    return f"{_combine(whole)}.{decimals}"


def normalize_numbers(text: str) -> str:
    """แทนคำบอกจำนวนไทยด้วยตัวเลข และทำหน่วยเปอร์เซ็นต์ให้เป็นรูปเดียว"""
    for word in _PERCENT_WORDS:
        text = text.replace(word, "%")

    out: list[str] = []
    index = 0
    while index < len(text):
        tokens, end = _tokenize(text, index)
        meaningful = [t for t in tokens if t != POINT]
        if meaningful:
            out.append(_render(tokens))
            index = end
        else:
            out.append(text[index])
            index += 1
    return "".join(out)
