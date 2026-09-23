"""ดึงศัพท์โป๊กเกอร์จาก glossary มาใช้เอียงการถอดเสียง

Whisper รับ initial_prompt เพื่อชี้นำคำที่คาดว่าจะเจอ การป้อนศัพท์อังกฤษ
จาก glossary ช่วยให้คงรูปอังกฤษแทนการทับศัพท์เป็นเสียงไทย
"""

from __future__ import annotations

import functools
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
GLOSSARY = ROOT / "harnesses" / "EN" / "glossary.md"
PROMPT_PREFIX = (
    "นี่คือคำถามภาษาไทยเรื่องโป๊กเกอร์ ผู้พูดใช้ภาษาไทยเป็นหลัก "
    "และแทรกศัพท์อังกฤษเหล่านี้: "
)
PROMPT_SUFFIX = " ให้ถอดเป็นภาษาไทยโดยคงศัพท์อังกฤษไว้ตามรูปเดิม"
MAX_PROMPT_CHARS = 620
# คำที่คนถามชาร์ตพรีฟล็อปพูดบ่อยแต่ glossary ไม่มี ถ้าไม่บอกไว้ cutoff จะถูกถอดเป็น บัตรทอด
SPOKEN_TERMS = (
    "under the gun", "UTG", "lojack", "hijack", "cutoff", "button", "small blind",
    "big blind", "raise first in", "RFI", "open", "3-bet", "4-bet", "shove", "all-in",
    "offsuit", "suited", "preflop", "preflop chart", "range",
)


HEADER_CELLS = frozenset({"english", "term", "ไทย", "thai"})


def _table_rows(text: str) -> list[list[str]]:
    """แถวเนื้อหาของตาราง markdown แถวแรกของแต่ละตารางคือหัวตารางจึงถูกตัดทิ้ง"""
    rows = []
    in_table = False
    for line in text.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        if "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or not cells[0]:
            continue
        if not in_table or cells[0].lower() in HEADER_CELLS:
            in_table = True
            continue
        rows.append(cells)
    return rows


@functools.lru_cache(maxsize=1)
def english_terms() -> tuple[str, ...]:
    """ศัพท์อังกฤษทั้งหมดจาก glossary เรียงตามที่ปรากฏ"""
    if not GLOSSARY.exists():
        return ()
    return tuple(row[0] for row in _table_rows(GLOSSARY.read_text(encoding="utf-8")))


@functools.lru_cache(maxsize=1)
def stream_terms() -> tuple[str, ...]:
    """ศัพท์ที่ส่งให้ตัวถอดเสียงทางสตรีม glossary ก่อน ตามด้วยคำพูดที่ใช้ถามชาร์ต

    Soniox รับรายการศัพท์ได้ยาวกว่า initial_prompt ของ Whisper มาก จึงเติมเพิ่มได้
    """
    terms = list(english_terms())
    seen = {term.lower() for term in terms}
    for term in SPOKEN_TERMS:
        if term.lower() not in seen:
            terms.append(term)
            seen.add(term.lower())
    return tuple(terms)


@functools.lru_cache(maxsize=1)
def bias_prompt() -> str:
    """ประโยคชี้นำสำหรับ Whisper ตัดให้ไม่เกินขีดจำกัดของ initial_prompt"""
    terms = english_terms()
    if not terms:
        return ""
    prompt = PROMPT_PREFIX
    for index, term in enumerate(terms):
        addition = term if index == 0 else f", {term}"
        if len(prompt) + len(addition) > MAX_PROMPT_CHARS:
            break
        prompt += addition
    return prompt + PROMPT_SUFFIX
