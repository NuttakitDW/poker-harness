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
# board หรือมือที่เขียนคั่นขีดอย่าง 6-5-4 หรือ A-K ถ้าอ่านว่า "6 ถึง 5 ถึง 4" ฟังไม่เป็นธรรมชาติ
# ตัวเลขสองตัวเรียงขึ้นอย่าง 3-5 ยังเป็นช่วงตัวเลข ส่วน 7-6 ที่เรียงลงหรือมีตัวอักษรเป็นไพ่
_BOARD = re.compile(r"(?<![\w.])[AKQJT2-9](?:-[AKQJT2-9])+(?![\w.])")
BOARD_MIN_DIGITS = 3
# มือที่เขียนติดกันอย่าง JJ63 หรือ KKQJ ต้องมีตัวอักษรอย่างน้อยหนึ่งตัว ตัวเลขล้วนอย่าง 65 แยกจากจำนวนไม่ได้
_HAND = re.compile(r"(?<![\w-])(?=[AKQJT2-9]*[AKQJT])[AKQJT2-9]{2,4}(?![\w-])")

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


def _read_board(match: re.Match) -> str:
    cards = match.group(0).split("-")
    if (len(cards) < BOARD_MIN_DIGITS and all(card.isdigit() for card in cards)
            and cards[0] < cards[-1]):
        return match.group(0)
    return " ".join(RANKS.get(card, card) for card in cards)


def _expand_cards(text: str) -> str:
    """แปลงไพ่อย่าง A♣ เป็นคำอ่านไทย เพราะเครื่องอ่านออกเสียงข้ามสัญลักษณ์ดอก"""
    text = _BOARD.sub(_read_board, text)
    text = _HAND.sub(lambda m: " ".join(RANKS.get(card, card) for card in m.group(0)), text)
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
