"""ตัววัดคุณภาพการถอดเสียงภาษาไทยสลับอังกฤษ

ภาษาไทยไม่เว้นวรรคระหว่างคำ จึงใช้ CER เป็นตัวหลัก และใช้ WER
เฉพาะกับโทเค็นอังกฤษเพื่อดูว่าศัพท์โป๊กเกอร์ถูกถอดถูกไหม
"""

from __future__ import annotations

import re
import unicodedata

from thai_numbers import normalize_numbers

_ENGLISH_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_PUNCT = re.compile(r"[^\w฀-๿]+")


def normalize(text: str) -> str:
    """ทำข้อความให้เทียบกันได้: รูปยูนิโคด ตัวพิมพ์ จำนวน และเครื่องหมายวรรคตอน

    ต้องแปลงจำนวนก่อนตัดเครื่องหมาย เพราะจุดทศนิยมและ % เป็นข้อมูล
    """
    folded = unicodedata.normalize("NFC", text).lower()
    counted = normalize_numbers(folded)
    return _PUNCT.sub(" ", counted).strip()


def _levenshtein(a: str, b: str) -> int:
    """ระยะแก้ไขแบบแถวเดียว ไม่แก้ไขอินพุต"""
    if not a:
        return len(b)
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, start=1):
        current = [i]
        for j, item_b in enumerate(b, start=1):
            cost = 0 if item_a == item_b else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """CER หลังตัดช่องว่างทั้งหมด เหมาะกับภาษาไทย"""
    ref = normalize(reference).replace(" ", "")
    hyp = normalize(hypothesis).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def english_terms(text: str) -> tuple[str, ...]:
    """ดึงโทเค็นอังกฤษ เช่น c-bet, SPR, ICM เพื่อตรวจ code-switching"""
    return tuple(t.lower() for t in _ENGLISH_TOKEN.findall(text))


def english_recall(reference: str, hypothesis: str) -> float:
    """สัดส่วนศัพท์อังกฤษในเฉลยที่โผล่ในผลถอดเสียง"""
    expected = english_terms(reference)
    if not expected:
        return 1.0
    produced = set(english_terms(hypothesis))
    return sum(1 for term in expected if term in produced) / len(expected)
