"""แปลงคำตอบให้พร้อมอ่านออกเสียง

โมเดลอาจแทรก markdown สัญลักษณ์ หรือสูตร ซึ่งเครื่องอ่านออกเสียงจะอ่านผิด
จึงต้องทำให้เป็นข้อความพูดล้วนก่อนส่งเข้า TTS
"""

from __future__ import annotations

import re

from loanwords import prefer_english

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_)(.+?)\1", re.DOTALL)
_URL = re.compile(r"https?://\S+")
_BLANKS = re.compile(r"\n{2,}")
_SPACES = re.compile(r"[ \t]{2,}")

SUITS = {
    "\u2660": " โพดำ ",
    "\u2665": " โพแดง ",
    "\u2666": " ข้าวหลามตัด ",
    "\u2663": " ดอกจิก ",
    "\u2664": " โพดำ ",
    "\u2661": " โพแดง ",
    "\u2662": " ข้าวหลามตัด ",
    "\u2667": " ดอกจิก ",
}
RANKS = {"A": "เอซ", "K": "เค", "Q": "คิว", "J": "แจ็ค", "T": "สิบ"}
_CARD = re.compile(r"\b([AKQJT2-9])(?=[\u2660-\u2667])")

CURRENCY = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")

SYMBOLS = (
    ("%", " เปอร์เซ็นต์ "),
    ("−", " ลบ "),
    ("–", " ถึง "),
    ("$", " ดอลลาร์ "),
    ("×", " คูณ "),
    ("÷", " หารด้วย "),
    ("≥", " มากกว่าหรือเท่ากับ "),
    ("≤", " น้อยกว่าหรือเท่ากับ "),
    ("→", " ไปเป็น "),
    ("&", " และ "),
    ("/", " ต่อ "),
    ("+", " บวก "),
    ("=", " เท่ากับ "),
)


def _strip_markdown(text: str) -> str:
    """เอาโครงสร้าง markdown ออก เหลือแต่ถ้อยคำ"""
    text = _CODE_FENCE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _EMPHASIS.sub(r"\2", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    return _NUMBERED.sub("", text)


def _expand_cards(text: str) -> str:
    """แปลงไพ่อย่าง A♣ เป็นคำอ่านไทย เพราะเครื่องอ่านออกเสียงข้ามสัญลักษณ์ดอก"""
    text = _CARD.sub(lambda m: RANKS.get(m.group(1), m.group(1)), text)
    for symbol, spoken in SUITS.items():
        text = text.replace(symbol, spoken)
    return text


def _expand_symbols(text: str) -> str:
    """แทนสัญลักษณ์ด้วยคำอ่าน โดยเว้นเครื่องหมายลบที่ติดกับตัวเลข"""
    text = CURRENCY.sub(r"\1 ดอลลาร์ ", text)
    text = re.sub(r"(?<=\d)-(?=\d)", " ถึง ", text)
    for symbol, spoken in SYMBOLS:
        text = text.replace(symbol, spoken)
    return text


def to_speech(text: str) -> str:
    """ข้อความพร้อมส่งเข้า TTS"""
    cleaned = prefer_english(_expand_symbols(_expand_cards(_strip_markdown(text))))
    cleaned = _BLANKS.sub(" ", cleaned).replace("\n", " ")
    return _SPACES.sub(" ", cleaned).strip()
