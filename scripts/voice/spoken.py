"""แปลงคำตอบให้พร้อมอ่านออกเสียง

โมเดลอาจแทรก markdown สัญลักษณ์ หรือสูตร ซึ่งเครื่องอ่านออกเสียงจะอ่านผิด
จึงต้องทำให้เป็นข้อความพูดล้วนก่อนส่งเข้า TTS
"""

from __future__ import annotations

import re

from loanwords import prefer_english
from thai_numbers import to_words

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

# มือ Hold'em ตัวย่ออย่าง A9o KQs AJs+ TT+ ถ้าปล่อยไว้เครื่องอ่านว่า "เอ เก้า โอ"
# suited กับ offsuit ส่งเป็นคำอังกฤษเพราะคนโป๊กเกอร์พูดทับศัพท์ และเครื่องอ่านคำอังกฤษได้ถูก
# ขอบเขตดูแค่อักษรอังกฤษกับตัวเลข เพราะโมเดลเขียนติดคำไทยอย่าง "มือA9oเป็น" ได้
_COMBO = re.compile(r"(?<![A-Za-z0-9])([AKQJT2-9])([AKQJT2-9])([so])(\+?)(?![A-Za-z0-9])")
_PAIR_UP = re.compile(r"(?<![A-Za-z0-9])([AKQJT2-9])\1\+(?![A-Za-z0-9])")
# ช่วงของมืออย่าง ATo-A8o หลังแปลงแล้วเหลือขีดคั่น ต้องอ่านว่า "ถึง"
_COMBO_RANGE = re.compile(r"(suited|offsuit) -")
COMBO_SHAPES = {"s": "suited", "o": "offsuit"}

# เครื่องอ่านออกเสียงอ่านเลขอารบิกเป็นภาษาอังกฤษบ้างเพี้ยนบ้าง จึงเขียนทุกจำนวนเป็นคำไทยก่อนส่ง
# เลขที่ติดตัวอักษรอังกฤษเป็นชื่อเฉพาะอย่าง PLO8 หรือ v2 ปล่อยไว้ ยกเว้นหน่วย bb และ k
_UNIT_GLUED = re.compile(r"(\d)(?=bb(?![a-z]))", re.IGNORECASE)
_THOUSANDS = re.compile(r"(?<![A-Za-z\d.])(\d+(?:\.\d+)?)\s?k(?![a-z])", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![A-Za-z\d.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![A-Za-z\d])"
                     r"|(?<![A-Za-z\d.,])\d+(?:\.\d+)?(?![A-Za-z\d])")
# 3-bet 4-bet คนเล่นพูดเป็นอังกฤษทั้งคำ
_N_BET = re.compile(r"(?<![\w.])([2-6])\s*-?\s*bet", re.IGNORECASE)
BET_NAMES = {"2": "two", "3": "three", "4": "four", "5": "five", "6": "six"}
# เลขซ้ำสองหลักอย่าง 33 คือไพ่คู่ ถ้าไม่มีหน่วยตามหลัง เช่น 33 เปอร์เซ็นต์ หรือ 55 ดอลลาร์
_POCKET_PAIR = re.compile(
    r"(?<![A-Za-z\d.,])([2-9])\1(?![A-Za-z\d.,%])"
    r"(?!\s*(?:เปอร์เซ็นต์|dollar|ดอลลาร์|บาท|bb|big|k\b|คน|ครั้ง|ปี|วัน|นาที|ชั่วโมง|เดือน|มือ|รอบ|ที่|ใบ|%))",
    re.IGNORECASE)

CURRENCY = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")

SYMBOLS = (
    ("%", " เปอร์เซ็นต์ "),
    ("−", " ลบ "),
    ("–", " ถึง "),
    ("$", " dollar "),
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


def _card(rank: str) -> str:
    return RANKS.get(rank, rank)


def _read_combo(match: re.Match) -> str:
    high, low, form, plus = match.groups()
    return f" {_card(high)} {_card(low)} {COMBO_SHAPES[form]}{' ขึ้นไป' if plus else ''} "


def _expand_cards(text: str) -> str:
    """แปลงไพ่อย่าง A♣ เป็นคำอ่านไทย เพราะเครื่องอ่านออกเสียงข้ามสัญลักษณ์ดอก"""
    text = _COMBO.sub(_read_combo, text)
    text = _COMBO_RANGE.sub(r"\1 ถึง ", text)
    text = _PAIR_UP.sub(lambda m: f" {_card(m.group(1))} {_card(m.group(1))} ขึ้นไป ", text)
    text = _BOARD.sub(_read_board, text)
    text = _HAND.sub(lambda m: " ".join(RANKS.get(card, card) for card in m.group(0)), text)
    text = _CARD.sub(lambda m: RANKS.get(m.group(1), m.group(1)), text)
    for symbol, spoken in SUITS.items():
        text = text.replace(symbol, spoken)
    return text


def _expand_symbols(text: str) -> str:
    """แทนสัญลักษณ์ด้วยคำอ่าน โดยเว้นเครื่องหมายลบที่ติดกับตัวเลข"""
    text = CURRENCY.sub(r"\1 dollar ", text)
    text = re.sub(r"(?<=\d)-(?=\d)", " ถึง ", text)
    for symbol, spoken in SYMBOLS:
        text = text.replace(symbol, spoken)
    return text


def _times_thousand(number: str) -> str:
    """5k เป็น 5000 และ 1.5k เป็น 1500 คิดแบบทศนิยมตรงตัวเพื่อไม่ให้ปัดเศษเพี้ยน"""
    whole, _, fraction = number.partition(".")
    return str(int(whole + fraction.ljust(3, "0")[:3]))


def _numbers_in_thai(text: str) -> str:
    """เขียนไพ่คู่เป็นชื่อไพ่ แล้วเขียนจำนวนที่เหลือทั้งหมดเป็นคำไทย"""
    text = _N_BET.sub(lambda m: f"{BET_NAMES[m.group(1)]}-bet", text)
    text = _POCKET_PAIR.sub(lambda m: f" {to_words(m.group(1))} {to_words(m.group(1))} ", text)
    text = _THOUSANDS.sub(lambda m: f" {to_words(_times_thousand(m.group(1)))} ", text)
    text = _UNIT_GLUED.sub(r"\1 ", text)
    return _NUMBER.sub(lambda m: f" {to_words(m.group(0).replace(',', ''))} ", text)


def to_speech(text: str) -> str:
    """ข้อความพร้อมส่งเข้า TTS"""
    cleaned = prefer_english(_expand_symbols(_expand_cards(_strip_markdown(text))))
    cleaned = _numbers_in_thai(cleaned)
    cleaned = _BLANKS.sub(" ", cleaned).replace("\n", " ")
    return _SPACES.sub(" ", cleaned).strip()
