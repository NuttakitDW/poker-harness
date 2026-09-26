"""ค้นตารางพรีฟล็อป GTO ที่ถอดจากคู่มือของ Jonathan Little

โมเดลคิดเลขเรนจ์เองไม่แม่น เคยตอบว่าสแตก 3 BB ที่ UTG ให้ shove แค่มือพรีเมียม
ซึ่งผิด ตารางพวกนี้จึงถูกยกมาวางไว้ในบริบทให้อ่านตรง ๆ แทนการเดา

ไฟล์ตารางสร้างด้วย scripts/build_preflop_charts.py ถ้ายังไม่ได้สร้างก็ไม่มีผลอะไร
"""

from __future__ import annotations

import dataclasses
import functools
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART_DIR = ROOT / "harnesses" / "charts"

RANKS = "AKQJT98765432"
STRENGTH = {rank: index for index, rank in enumerate(RANKS)}
ACTION_NAMES = {"raise": "raise", "call": "call", "fold": "fold"}
CODE_ACTIONS = {"R": "raise", "C": "call", "F": "fold", "-": "none"}

POSITIONS = ("UTG+1", "UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB")
POSITION_WORDS = {
    "utg+1": "UTG+1", "utg1": "UTG+1", "ยูทีจีหนึ่ง": "UTG+1",
    "utg": "UTG", "ยูทีจี": "UTG",
    "lj": "LJ", "lojack": "LJ", "โลแจ็ค": "LJ",
    "hj": "HJ", "hijack": "HJ", "ไฮแจ็ค": "HJ",
    "co": "CO", "cutoff": "CO", "คัตออฟ": "CO", "คัทออฟ": "CO",
    # ตัวถอดเสียงเคยเขียน cutoff เป็นคำไทยที่เสียงใกล้กัน
    "บัตรทอด": "CO", "คัทอ๊อฟ": "CO", "คัตอ๊อฟ": "CO",
    "btn": "BTN", "button": "BTN", "ปุ่ม": "BTN", "บัตตัน": "BTN",
    "dealer": "BTN", "ดีลเลอร์": "BTN",
    "sb": "SB", "smallblind": "SB", "สมอลบลายด์": "SB",
    "bb": "BB", "bigblind": "BB", "บิ๊กบลายด์": "BB",
    # ตัวถอดเสียงเขียนบิ๊กบลายด์ที่หมายถึงที่นั่งเป็นบิ๊กบายบ่อยมาก สแตกอย่าง 25 บิ๊กบาย ถูกตัดออกไปก่อนแล้ว
    "บิ๊กบาย": "BB", "บิกบาย": "BB", "บิ๊กบลาย": "BB",
    "สมอลบาย": "SB", "สมอลบลาย": "SB",
}
SCENARIO_WORDS = (
    ("6-Bet", ("6-bet", "6bet", "six bet", "หกเบ็ท")),
    ("5-Bet", ("5-bet", "5bet", "five bet", "ห้าเบ็ท")),
    ("4-Bet", ("4-bet", "4bet", "four bet", "โฟร์เบ็ท", "สี่เบ็ท")),
    ("3-Bet", ("3-bet", "3bet", "three bet", "ทรีเบ็ท", "สามเบ็ท")),
    ("Limp", ("limp", "ลิมพ์", "ลิมป์")),
    ("RFI", ("rfi", "raise first in", "เปิดเป็นคนแรก", "เปิดก่อน", "open", "เปิดมือ", "เปิด",
             "shove", "push", "ออลอิน", "all in", "all-in", "ยัดหมด", "ลงหมด")),
)
TOURNAMENT_WORDS = ("tournament", "mtt", "ทัวร์", "icm", "bubble", "บับเบิล", "sng", "shove",
                    "push", "ออลอิน", "all in", "all-in")
# ขอดูชาร์ตหรือเรนจ์ของตำแหน่งเดียวโดยไม่บอกว่าเจอใคร คนเล่นหมายถึงชาร์ตเปิดเป็นคนแรก
# คำว่าพรีฟล็อปอยู่ในลิสต์ด้วย เพราะตัวถอดเสียงชอบได้ยินคำว่าชาร์ตเป็นคำอื่น เช่น ฉาด
CHART_WORDS = ("ชาร์ต", "ชาร์ท", "chart", "เรนจ์", "range", "ตาราง",
               "preflop", "pre-flop", "พรีฟลอป", "พรีฟล็อป")
HOLD_WORDS = ("ถือ", "hold", "ได้ไพ่", "ได้มือ")
# คำขอตารางยังมีผลอยู่ถ้าพูดไว้ไม่เกินเท่านี้ตา เก่ากว่านั้นถือว่าเปลี่ยนเรื่องแล้ว
CHART_CARRY_TURNS = 2
CASH_WORDS = ("cash", "แคช", "เงินสด", "ring", "ริงเกม", "zoom")
# ชาร์ตที่เจอคู่มือ ช่อง raise คือการรีเรสกลับหนึ่งขั้นจากสถานการณ์นั้น
RAISE_MEANS = {"RFI": "3-bet", "Limp": "iso-raise", "3-Bet": "4-bet", "4-Bet": "5-bet"}
# คำที่ตามหลังชื่อตำแหน่งทันที บอกว่าตำแหน่งนั้นเปิดหรือ 3-bet
_OPENS = re.compile(r"\s*(?:เปิด|โอเพ่น|โอเพน|open|raise\s*first|rfi)")
_THREE_BETS = re.compile(r"\s*(?:3\s*-?\s*bet|three\s*bet|ทรีเบ็ท|สามเบ็ท)")
# "โดน 3-bet" หรือ "โดน BB 3-bet" แปลว่าคนถามคือคนเปิดที่ถูก 3-bet กลับ
_FACING_THREE_BET = re.compile(r"(?:โดน|เจอ).{0,15}?(?:3bet|threebet|ทรีเบ็ท|สามเบ็ท)")

# ตัวถอดเสียงเขียนบิ๊กบลายด์ได้หลายแบบ เช่น บิ๊กบาย บิกบลาย จึงจับแค่ต้นคำ
_STACK = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*(?:bb|big\s*blind|บีบี|บิ๊?กบ(?:ลาย|าย)(?:ด์|ส์)?)",
                    re.IGNORECASE)

# ขนาดโต๊ะ heads-up คือสองคน ตัวถอดเสียงเขียนเป็นไทยได้หลายแบบ ส่วน 6-max 3 handed โต๊ะ 9 คน บอกเลขตรง ๆ
_HEADS_UP = re.compile(r"(?<![a-z])(?:heads?\s*-?\s*up|hu)(?![a-z])|เฮด(?:ส์)?อัพ|ฮัดอัพ|ตัวต่อตัว")
_TABLE_SIZE = re.compile(r"(?<!\d)([2-9])\s*-?\s*(?:max|han(?:d?e)d|คน)")

# ขอ push/fold ตรง ๆ หรือพูดถึงการยัดหมด ใช้ solver แม้สแตกเกิน 15bb
_PUSH_FOLD = re.compile(r"push\s*[-/]?\s*fold|(?<![a-z])(?:jam\w*|shov\w*|push\w*|all\s*-?\s*in)(?![a-z])"
                        r"|ออลอิน|แจม|ยัดหมด|ลงหมด")

# ใครเป็นคนยัดหมด "UTG jam" คำตามหลังตำแหน่ง หรือ "คน jam เป็น UTG" คำนำหน้าตำแหน่ง
_JAM_WORD = r"(?:jam\w*|shov\w*|push\w*|all\s*-?\s*in|ออลอิน|แจม|ยัดหมด|ลงหมด)"
# คำเสริมระหว่างตำแหน่งกับ action ที่คนพูดจริง "Button ก็ all-in มาด้วย"
_FILLER = r"(?:\s*(?:ก็|also|เอง|ได้))?"
_JAMS_AFTER = re.compile(rf"{_FILLER}\s*{_JAM_WORD}")
_JAMS_BEFORE = re.compile(rf"{_JAM_WORD}\s*(?:มา)?\s*(?:เป็น|จาก|from|by)\s*$")
_JAM_LOOKBACK = 20
# push/fold คนที่ call คนยัดก็ลงหมดเหมือนกัน "button call" จึงนับเป็นคนยัดด้วย เว้นแต่เป็นคนถามเอง
_CALLS_AFTER = re.compile(rf"{_FILLER}\s*(?:call\w*|คอล|โคล)")
# "เราอยู่ small blind" หรือ "I'm in the SB" ตำแหน่งหลังคำนี้คือคนถาม
_HERO_BEFORE = re.compile(r"(?:เรา|ผม|ฉัน|i'?m|i\s+am|we'?re|we\s+are|hero)\s*(?:อยู่|นั่ง|เป็น|in|at|on)?"
                          r"\s*(?:ที่|ตำแหน่ง|the)?\s*$")

# ante ต่อคน "ante 12.5%" "ante 0.2bb" หรือไม่มีหน่วย ตั้งแต่ 1 ขึ้นไปถือเป็น % ของ BB ต่ำกว่านั้นเป็น bb
_ANTE = re.compile(r"(?:ante|แอนตี้|แอนติ)\s*(\d+(?:\.\d+)?)\s*(%|เปอร์เซ็นต์|bb|บีบี)?")
_NO_ANTE = re.compile(r"no\s*ante|without\s*(?:an\s*)?ante|ไม่มี\s*(?:ante|แอนตี้|แอนติ)")
# BB จ่าย ante แทนทั้งโต๊ะ "bb ante" "big blind ante" หรือบอกว่าเป็นทัวร์ live (ค่าเริ่ม 1bb)
# bb ต้องไม่ต่อจากตัวเลข "10bb ante 12.5%" คือสแตก 10bb กับ ante ทุกคน ไม่ใช่ BB ante
_BB_ANTE = re.compile(r"(?<![\d.])(?<![\d.]\s)(?:bb|big\s*blind|บีบี|บิ๊กบลายด์)\s*-?\s*(?:ante|แอนตี้|แอนติ)")
_LIVE = re.compile(r"(?<![a-z])live(?![a-z])|ไลฟ์")

# เงินรางวัลแต่ละอันดับ "icm 50/30/20" "payout 50 30 20" "รางวัล 50%/30%/20%" เปลี่ยนชาร์ตเป็น ICM
# เลขที่ตามด้วย bb หรือขนาดโต๊ะไม่ใช่รางวัล "icm 50/30/20 4 handed 10bb" คือรางวัลสามอันดับ
_PRIZE = (r"\d+(?:\.\d+)?(?![\d.])(?!\s*(?:bb|big\s*blind|บีบี|บิ๊?กบ|-?\s*max|han(?:d?e)d|คน))"
          r"\s*%?")
_PAYOUTS = re.compile(rf"(?:(?<![a-z])icm|payouts?|prizes?|ไอซีเอ็ม|เงินรางวัล|รางวัล)\s*:?\s*"
                      rf"({_PRIZE}(?:\s*[/,\-]?\s*{_PRIZE})+)")
# พูดแค่ icm ไม่บอกรางวัล คือ bubble ของเกม live (pushfold_chart.stage) ส่วน chip ev คือกลับไปไม่ใช้ ICM
_ICM_WORD = re.compile(r"(?<![a-z])icm(?![a-z])|ไอซีเอ็ม")
# ช่วงของทัวร์ที่เรียกชื่อ bubble คือเกือบถึงเงิน final table คือทุกคนที่เหลืออยู่โต๊ะนี้
_BUBBLE = re.compile(r"bubble|บับเบิ้?ล")
_FINAL_TABLE = re.compile(r"final\s*table|(?<![a-z])ft(?![a-z])|ไฟนอล\s*เทเบิ้?ล|โต๊ะสุดท้าย")
_CHIP_EV = re.compile(r"chip\s*-?\s*ev|(?<![a-z])c\s*-?\s*ev(?![a-z])|ชิป\s*อีวี")  # cev = chip ev
# GGPoker All-in or Fold คือเกม cash ที่ทุกคนมี 10bb ตัดคำออกก่อน ไม่ให้ all-in ในชื่อเกมถูกอ่านเป็นคนยัด
_AOF = re.compile(r"(?<![a-z])aof(?![a-z])|all\s*-?\s*in\s*(?:or|/|-)\s*fold|ออลอิน\s*(?:หรือ|ออร์)\s*โฟลด์")

# ช่วงของทัวร์ "50% left" "เหลือ 50%" "80% field" "field 80%" "120 left" "เหลือ 120 คน" คนลง "field 1000" "300 entrants"
# จ่ายกี่ % "paid 12%" สแตกเฉลี่ยโต๊ะอื่น "avg 25bb" ตัดออกก่อนอ่านสแตก ขนาดโต๊ะ และรางวัล
_NUMBER = r"(\d+(?:\.\d+)?)"
_PERCENT = r"\s*(?:%|เปอร์เซ็นต์)"
_LEFT_PCT = re.compile(rf"{_NUMBER}{_PERCENT}\s*(?:of\s*(?:the\s*)?field\s*)?(?:left|remain\w*)"
                       rf"|{_NUMBER}{_PERCENT}\s*(?:of\s*(?:the\s*)?)?field(?!\s*size)"
                       rf"|field\s*{_NUMBER}{_PERCENT}"
                       rf"|(?:คง)?เหลือ\s*{_NUMBER}{_PERCENT}")
_LEFT_COUNT = re.compile(r"(?<![\d.])(\d+)\s*(?:players?\s*)?(?:left|remain\w*)(?![a-z])"
                         r"|(?:คง)?เหลือ\s*(\d+)\s*คน")
_ENTRANTS = re.compile(r"(?:field(?:\s*size)?|entrants?|runners?|คนลง(?:แข่ง)?|ผู้เข้าแข่ง(?:ขัน)?)\s*(\d+)"
                       r"|(?<![\d.])(\d+)\s*(?:entrants?|runners?|entries)")
_PAID = re.compile(rf"(?:paid|itm|จ่าย(?:รางวัล)?)\s*{_NUMBER}{_PERCENT}|{_NUMBER}{_PERCENT}\s*(?:paid|itm)")
_BB_UNIT = r"(?:bb|big\s*blinds?|บีบี|บิ๊?กบ(?:ลาย|าย)(?:ด์|ส์)?)"
_AVERAGE = re.compile(rf"(?:avg|average|สแตกเฉลี่ย|เฉลี่ย)\s*(?:stack\s*)?{_NUMBER}\s*{_BB_UNIT}?"
                      rf"|(?<![\d.]){_NUMBER}\s*{_BB_UNIT}\s*(?:avg|average|เฉลี่ย)(?!\s*(?:stack\s*)?\d)")

# คำบอกว่าดอกเดียวกันหรือต่างดอก ตัวถอดเสียงเขียนได้ทั้งอังกฤษและไทย
_SUIT_WORD = r"(?i:offsuit|off-suit|off|suited|suit|ออฟสูท|ออฟ|สูท|คนละสี|คนละดอก|ต่างดอก|สีเดียวกัน|ดอกเดียวกัน)"
# คำบอกดอกที่แปลว่าต่างดอก ที่เหลือแปลว่าดอกเดียวกัน
_OFFSUIT_HINTS = ("off", "ออฟ", "คนละ", "ต่าง")
# ข้อความเสียงเรียกไพ่เป็นคำ "Jack 2 off" "แจ็ค 2 ออฟ" แปลงเป็นตัวอักษรไพ่ก่อนหามือ
# พหูพจน์คือคู่ "pocket jacks" เป็น JJ ส่วน "ten big blinds" ไม่มีไพ่ใบที่สอง จึงไม่กลายเป็นมือ
_CARD_WORDS = (
    (r"aces", "AA"), (r"kings", "KK"), (r"queens", "QQ"), (r"jacks", "JJ"), (r"tens", "TT"),
    (r"ace|เอซ", "A"), (r"king|คิง", "K"), (r"queen|ควีน", "Q"), (r"jack|แจ็ค|แจ๊ค|แจค", "J"),
    (r"ten|เท็น", "T"),
)
# "pocket queen" "pocket 8" คือคู่ แม้พูดเป็นเอกพจน์
_POCKET = re.compile(r"(?i)pocket\s*(aces?|kings?|queens?|jacks?|tens?|[2-9akqjt])(?![a-z0-9])")
_RANK_WORDS = {"ace": "A", "king": "K", "queen": "Q", "jack": "J", "ten": "T"}


def _rank_of(word: str) -> str:
    word = word.lower().rstrip("s") if len(word) > 1 else word
    return _RANK_WORDS.get(word, word.upper())


_CARD_WORD_PATTERNS = tuple((re.compile(rf"(?i)(?<![a-z])(?:{words})(?![a-z])"), rank)
                            for words, rank in _CARD_WORDS)
# คนไทยอ่าน T ว่าสิบ พูด T8 ว่าสิบแปดแล้วตัวถอดเสียงเขียนเป็น 18 ถือเป็นมือเฉพาะเมื่อตามด้วยคำบอกดอก
_TEEN_HAND = re.compile(rf"(?<!\d)1([2-9])(?=\s*{_SUIT_WORD})")
_TEN = re.compile(r"(?<!\d)10(?!\d)")
# ตัวอักษรไพ่ต้องเป็นตัวใหญ่ ไม่งั้นคำอังกฤษอย่าง at จะกลายเป็นมือ AT
_HAND = re.compile(rf"(?<![A-Za-z0-9])([AKQJT2-9])\s?[,\-]?\s?([AKQJT2-9])"
                   rf"(?:\s*({_SUIT_WORD})|([so]))?(?![A-Za-z0-9])")
# เลขคู่ติดกันอย่าง 99 คือพ็อกเก็ตแพร์ เว้นแต่อยู่ในบริบทตัวเลข เช่น เหลือ 55 คน, 33/33/33, field 88
_COUNT_BEFORE = re.compile(r"(?i)(?:[/.]|field(?:\s*size)?|entrants?|avg|average|เฉลี่ย|paid|itm"
                           r"|จ่าย(?:รางวัล)?|ante|เหลือ|คนลง(?:แข่ง)?|ผู้เข้าแข่ง(?:ขัน)?)\s*$")
_COUNT_AFTER = re.compile(r"(?i)\s*(?:[%/.]|เปอร์|percent|คน|left|players?|remain|han(?:d?e)d|max"
                          r"|entrants?|runners?|entries|paid|itm)")


def _digit_pair(text: str, match: re.Match) -> bool:
    """เลขเดียวกันสองตัวติดกันที่ไม่ได้เป็นจำนวนคน เปอร์เซ็นต์ หรือรางวัล"""
    first, second = match.group(1), match.group(2)
    return (first == second and first.isdigit() and match.end(2) - match.start(1) == 2
            and not _COUNT_BEFORE.search(text[:match.start()])
            and not _COUNT_AFTER.match(text, match.end()))


@dataclasses.dataclass(frozen=True)
class Request:
    """สิ่งที่ถอดได้จากคำถามว่าผู้ใช้ถามถึงสถานการณ์ไหน"""

    game: str | None = None
    stack: float | None = None  # สแตกเป็น bb เลขเต็มเก็บเป็น int ทศนิยมอย่าง 5.5 เก็บเป็น float
    hero: str | None = None
    villain: str | None = None
    scenario: str | None = None
    players: int | None = None
    shovers: tuple[str, ...] = ()  # ทุกตำแหน่งที่ยัดหมดมาก่อนคนถาม เรียงตามที่พูด
    pushfold: bool = False
    ante: float | None = None  # ante ต่อคนที่จ่ายเป็น bb, 0 คือไม่มี ante, None คือไม่ได้บอก
    ante_mode: str | None = None  # "each" ทุกคนจ่าย, "bb" BB จ่ายแทนทั้งโต๊ะ, None คือไม่ได้บอก
    payouts: tuple[float, ...] | None = None  # รางวัลอันดับ 1, 2, ... () คือ chip EV, None คือไม่ได้บอก
    icm: bool = False                  # พูดว่า icm หรือ bubble เฉย ๆ ไม่บอกรางวัล
    left_pct: float | None = None      # เหลือกี่ % ของคนลง
    players_left: int | None = None    # เหลือกี่คน
    entrants: int | None = None        # คนลงทั้งหมด
    paid_pct: float | None = None      # จ่ายรางวัลกี่ % ของคนลง
    field_avg: float | None = None     # สแตกเฉลี่ยของคนที่โต๊ะอื่น เป็น bb
    stage_word: str | None = None      # "bubble" หรือ "final" ช่วงของทัวร์ที่เรียกชื่อ ไม่บอกจำนวนคน
    aof: bool = False                  # GGPoker All-in or Fold ใช้โต๊ะและค่าธรรมเนียมของเกมนั้น

    @property
    def usable(self) -> bool:
        """ข้อมูลพอจะเจาะจงชาร์ตได้จริงไหม"""
        return bool(self.hero and (self.scenario or self.villain))


@functools.lru_cache(maxsize=1)
def books() -> tuple[dict, ...]:
    """ตารางทั้งหมดที่ถอดไว้ ถ้ายังไม่ได้สร้างไฟล์ก็คืนว่าง"""
    loaded = []
    for path in sorted(CHART_DIR.glob("preflop-*.json")):
        try:
            loaded.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return tuple(loaded)


def _mentions(text: str) -> list[tuple[int, int, str]]:
    """ทุกจุดที่พูดถึงตำแหน่ง (ต้นคำ, ท้ายคำ, ตำแหน่ง) เรียงตามลำดับในข้อความ

    ภาษาไทยไม่เว้นวรรคระหว่างคำ จึงหาคำไทยแบบข้อความย่อย ส่วนคำอังกฤษต้องเป็นคำเต็ม
    ไม่งั้น co ในคำอื่นจะถูกอ่านเป็นตำแหน่ง cutoff
    """
    found: list[tuple[int, int, str]] = []
    for word, name in POSITION_WORDS.items():
        pattern = (rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9+])" if word.isascii()
                   else re.escape(word))
        found.extend((match.start(), match.end(), name)
                     for match in re.finditer(pattern, text))
    return sorted(found)


def _positions(mentions: list[tuple[int, int, str]]) -> list[str]:
    """ตำแหน่งที่ถูกพูดถึง ไม่ซ้ำ เรียงตามครั้งแรกที่โผล่"""
    return list(dict.fromkeys(name for _, _, name in mentions))


def _seat_doing(text: str, mentions: list[tuple[int, int, str]], action: re.Pattern) -> str | None:
    """ตำแหน่งแรกที่ตามด้วยคำบอกการกระทำทันที เช่น "Button เปิด" หรือ "BB 3-bet" """
    return next((name for _, end, name in mentions if action.match(text, end)), None)


def _roles(text: str, found: list[str],
           scenario: str | None) -> tuple[str | None, str | None, str | None]:
    """เลือกว่าใครคือผู้ถาม (hero) ใครคือคู่มือ จากบทบาทที่พูด ไม่ใช่จากลำดับคำ

    คนเล่นพูดชื่อคนเปิดก่อน เช่น "Button เปิด แล้ว BB 3-bet อะไรได้" คนถามคือ BB
    ส่วนเรนจ์ 3-bet ของ BB อยู่ในชาร์ตฝั่ง BB เจอการเปิด (ช่อง raise) ไม่ใช่ชาร์ต 3-Bet
    ซึ่งเป็นฝั่งคนเปิดที่โดน 3-bet กลับมา
    """
    hero = found[0] if found else None
    villain = found[1] if len(found) > 1 else None
    mentions = _mentions(text)
    opener = _seat_doing(text, mentions, _OPENS)
    # "BB 3-bet ใส่ button" คือ BB จะ 3-bet คนเปิด เรนจ์อยู่ในช่อง raise ของชาร์ต BB เจอการเปิด
    raiser = _seat_doing(text, mentions, _THREE_BETS)
    if (opener is None and raiser is not None and scenario == "3-Bet" and len(found) > 1
            and not _FACING_THREE_BET.search(_squash(text))):
        return raiser, next(name for name in found if name != raiser), "RFI"
    if len(found) < 2 or opener is None or scenario not in (None, "RFI", "3-Bet"):
        return hero, villain, scenario
    raiser = _seat_doing(text, mentions, _THREE_BETS)
    other = raiser if raiser not in (None, opener) else next(
        name for name in found if name != opener)
    if _FACING_THREE_BET.search(_squash(text)):
        return opener, other, "3-Bet"
    return other, opener, "RFI"


def _before(text: str, start: int, pattern: re.Pattern) -> bool:
    return bool(pattern.search(text[max(0, start - _JAM_LOOKBACK):start]))


def _jammers(text: str, mentions: list[tuple[int, int, str]]) -> list[str]:
    """ทุกตำแหน่งที่ยัดหมดมา "UTG jam" หรือ "คน jam เป็น UTG" ไม่ซ้ำ เรียงตามที่พูด"""
    return list(dict.fromkeys(name for start, end, name in mentions
                              if _JAMS_AFTER.match(text, end) or _before(text, start, _JAMS_BEFORE)))


# ลำดับการเล่นก่อน flop โต๊ะเต็ม ใช้ตัดสินว่าใครเล่นก่อนใคร
ACTION_ORDER = ("UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB")


def _acts_before(seat: str, other: str) -> bool:
    return (seat in ACTION_ORDER and other in ACTION_ORDER
            and ACTION_ORDER.index(seat) < ACTION_ORDER.index(other))


def _marked_hero(text: str, mentions: list[tuple[int, int, str]]) -> str | None:
    return next((name for start, _, name in mentions if _before(text, start, _HERO_BEFORE)), None)


def seat_mentions(text: str) -> list[tuple[int, int, str]]:
    """ทุกจุดที่พูดถึงตำแหน่งในข้อความที่ผ่าน normalize_seats แล้ว"""
    return _mentions(text)


# พิมพ์ชื่อตำแหน่งผิดหนึ่งตัว เช่น btbn ugt cutof ยังอ่านเป็นตำแหน่งได้ คำอังกฤษธรรมดาที่ใกล้ btn ไม่นับ
_WORD = re.compile(r"(?<![a-z0-9])[a-z]{3,}(?![a-z0-9+])")
_TYPO_TARGETS = tuple(word for word in POSITION_WORDS if word.isascii() and word.isalpha() and len(word) >= 3)
_NOT_SEATS = {"bin", "ban", "bun", "ben", "ton"}


def _one_edit(a: str, b: str) -> bool:
    """a กับ b ต่างกันไม่เกินหนึ่งตัว เพิ่ม ลบ แทน หรือสลับตัวติดกัน"""
    if a == b or abs(len(a) - len(b)) > 1:
        return a == b
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


# ตัวถอดเสียงเขียนชื่อตำแหน่งอังกฤษเป็นไทยตามเสียงได้หลายแบบ ข้อความเสียงจริงจาก Discord:
# "บัตท่อน" "สมอลไบล์" "บิ๊กไบร์ท" จึงแปลงเป็นชื่อมาตรฐานก่อนอ่าน "10 บิ๊กไบร์ท" จะได้เป็นสแตกด้วย
_BLIND_SOUND = r"(?:บลาย|บาย|ไบล์|ไบล|ไบร์ท|ไบรท์|ไบร์|ไบ)(?:ด์|ส์|ท์)?"
_SOUNDED_SEATS = (
    (re.compile(rf"สมอล\s*{_BLIND_SOUND}"), "sb"),
    (re.compile(rf"บิ๊?ก\s*{_BLIND_SOUND}"), "bb"),
    (re.compile(r"บั[ตท](?:ตัน|ท่อน|ทอน|ต้น|ต้อน|ทั่น|ตั้น|ท้อน)"), "btn"),
)


def _sounded_out_seats(text: str) -> str:
    for pattern, seat in _SOUNDED_SEATS:
        text = pattern.sub(f" {seat} ", text)
    return text


def normalize_thai(text: str) -> str:
    """ตัวถอดเสียงเขียนสระอำได้สองแบบ (ํ + า กับ ำ) ทำให้เป็นแบบเดียว คำอย่าง ตำแหน่ง จะได้จับได้"""
    return text.replace("\u0e4d\u0e32", "\u0e33")


def _fix_seat_typos(text: str) -> str:
    def fix(match: re.Match) -> str:
        word = match.group(0)
        if word in POSITION_WORDS or word in _NOT_SEATS:
            return word
        return next((seat for seat in _TYPO_TARGETS if _one_edit(word, seat)), word)
    return _WORD.sub(fix, _sounded_out_seats(normalize_thai(text)))


def normalize_seats(text: str) -> str:
    """ตัวพิมพ์เล็ก แก้ชื่อตำแหน่งที่พิมพ์ผิด และรวม big blind เป็นคำเดียว ตำแหน่งที่ seat_mentions คืนอิงข้อความนี้"""
    return _spaced_blinds(_fix_seat_typos(text.lower()))


def _squash(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text)


def _spaced_blinds(text: str) -> str:
    """ตัวถอดเสียงเขียน big blind แยกสองคำ รวมให้เป็นคำเดียวกับที่ตารางคำรู้จัก"""
    return re.sub(r"\b(big|small)[\s\-]+blind", r"\1blind", text)


def parse(question: str) -> Request:
    """อ่านคำถามแล้วเดาว่าเป็นสถานการณ์ไหน"""
    lowered = _fix_seat_typos(question.lower())
    aof = bool(_AOF.search(lowered))
    ante, ante_mode, lowered = _read_ante(_AOF.sub(" ", lowered))
    stage, lowered = _read_stage(lowered)
    payouts, lowered = _read_payouts(lowered)
    icm = payouts is None and bool(_ICM_WORD.search(lowered))
    stage_word = ("final" if _FINAL_TABLE.search(lowered)
                  else "bubble" if _BUBBLE.search(lowered) else None)
    stack = _STACK.search(lowered)

    game = None
    if any(word in lowered for word in TOURNAMENT_WORDS):
        game = "tournament"
    elif any(word in lowered for word in CASH_WORDS):
        game = "cash"

    # ตัวถอดเสียงเขียน first-in บ้าง first in บ้าง เทียบแบบไม่สนขีดและช่องว่าง
    squashed = _squash(lowered)
    scenario = next((name for name, words in SCENARIO_WORDS
                     if any(_squash(word) in squashed for word in words)), None)

    # ตัด "80BB" ออกก่อนหาตำแหน่ง ไม่งั้น BB ที่หมายถึงหน่วยชิปจะถูกอ่านเป็นตำแหน่ง
    seats = _spaced_blinds(_STACK.sub(" ", lowered))
    found = _positions(_mentions(seats))
    hero, villain, scenario = _roles(seats, found, scenario)
    # มีคนยัดหมดมา คนถามคือคนที่บอกว่า "เราอยู่" หรืออีกคนที่ไม่ได้ยัด ชาร์ตคือเจอ All-In
    shovers: tuple[str, ...] = ()
    mentions = _mentions(seats)
    jammers = _jammers(seats, mentions) if len(found) > 1 and scenario in (None, "RFI") else []
    marked = _marked_hero(seats, mentions)
    if not jammers and marked and _PUSH_FOLD.search(seats):
        # "มีคน all-in มาก่อน 1 คน จากตำแหน่ง UTG เราอยู่ hijack" บอกคนถามชัด แต่ไม่ได้วางคำ jam
        # ติดตำแหน่ง ที่นั่งอื่นที่เล่นก่อนคนถามจึงเป็นคนแจม ที่นั่งหลังคนถามยังไม่ได้เล่น
        jammers = [name for name in found if name != marked and _acts_before(name, marked)]
    if jammers:
        caller = marked or next((n for n in found if n not in jammers), None)
        callers = [name for _, end, name in mentions if _CALLS_AFTER.match(seats, end)]
        shovers = tuple(dict.fromkeys(name for name in jammers + callers if name != caller))
        if caller and shovers:
            hero, villain, scenario = caller, shovers[0], "All-In"
        else:
            shovers = ()
    if "vs" in lowered or "เจอ" in lowered or "โดน" in lowered:
        scenario = scenario or "RFI"
    # ถือมืออยู่ตำแหน่งเดียวโดยไม่มีใครเปิดมาก่อน คือถามว่าควรเปิดมือนี้ไหม
    # มือคู่ตัวเลขอย่าง 33 ไม่ถูกนับเป็นมือเพราะชนกับเปอร์เซ็นต์ จึงดูคำว่าถือด้วย
    asks_open = (any(word in lowered for word in (*CHART_WORDS, *HOLD_WORDS))
                 or bool(hands_in(question)))
    if hero and not villain and asks_open:
        scenario = scenario or "RFI"
    size = _TABLE_SIZE.search(lowered)
    players = 2 if _HEADS_UP.search(lowered) else int(size.group(1)) if size else None
    return Request(game=game, stack=_stack_value(stack.group(1)) if stack else None,
                   hero=hero, villain=villain, scenario=scenario, players=players, shovers=shovers,
                   pushfold=bool(_PUSH_FOLD.search(lowered)), ante=ante, ante_mode=ante_mode,
                   payouts=payouts, icm=icm, stage_word=stage_word, aof=aof, **stage)


def carry(question: str, earlier: list[str]) -> str:
    """เติมสแตกและประเภทเกมที่เคยพูดไว้ในคำถามก่อน ๆ ถ้าคำถามนี้ไม่ได้บอก

    คำถามต่อเนื่องอย่าง "ไม่มีได้ยังไง" ยืมได้แค่คำถามก่อนหน้าหนึ่งตา ถ้าตานั้นไม่ได้บอกสแตก
    เคยได้ชาร์ต cash 100BB ทั้งที่คุยกันเรื่องทัวร์ 20BB มาตลอด
    """
    request = parse(question)
    extra = []
    for text in reversed(earlier):
        said = parse(text)
        if request.stack is None and said.stack is not None:
            extra.append(f"{said.stack}BB")
            request = dataclasses.replace(request, stack=said.stack)
        if request.game is None and said.game is not None:
            extra.append(said.game)
            request = dataclasses.replace(request, game=said.game)
    # ขอตาราง range แล้วตาถัดมาค่อยบอกตำแหน่ง เคยได้คำตอบว่าส่งตารางให้ดูไม่ได้
    recent = " ".join(earlier[-CHART_CARRY_TURNS:]).lower()
    if (request.hero and not request.usable
            and any(word in recent for word in CHART_WORDS)):
        extra.append("range")
    return " ".join((question, *extra))


def hands_in(question: str) -> list[str]:
    """มือที่ผู้ใช้ถามถึง เช่น A8o หรือ KQs ถ้าไม่บอกดอกคืนทั้ง suited และ offsuit"""
    text = _STACK.sub(" ", question)
    text = _POCKET.sub(lambda m: _rank_of(m.group(1)) * 2, text)
    for pattern, rank in _CARD_WORD_PATTERNS:
        text = pattern.sub(rank, text)
    text = _TEN.sub("T", _TEEN_HAND.sub(r"T\1", text))
    found: list[str] = []
    for match in _HAND.finditer(text):
        first, second, word, letter = match.groups()
        suit = letter
        if word:
            suit = "o" if any(hint in word.lower() for hint in _OFFSUIT_HINTS) else "s"
        # ตัวเลขล้วนไม่มีคำบอกดอก เช่น 98 เปอร์เซ็นต์ ไม่ใช่มือ
        if suit is None and first.isdigit() and second.isdigit() and not _digit_pair(text, match):
            continue
        high, low = sorted((first, second), key=STRENGTH.get)
        if high == low:
            names = [high * 2]
        elif suit:
            names = [f"{high}{low}{suit}"]
        else:
            names = [f"{high}{low}s", f"{high}{low}o"]
        found.extend(name for name in names if name not in found)
    return found


def _read_ante(text: str) -> tuple[float | None, str | None, str]:
    """(ante เป็น bb, ใครจ่าย, ข้อความที่ตัดคำบอก ante ออกแล้ว)

    ตัดออกเพื่อไม่ให้เลขของ ante ถูกอ่านเป็นสแตก และ bb ใน "bb ante" ถูกอ่านเป็นที่นั่ง BB
    ante ไม่มีหน่วยของทุกคน ตั้งแต่ 1 ขึ้นไปเป็น % ของ BB ส่วน BB ante ไม่มีหน่วยเป็น bb เสมอ
    """
    if _NO_ANTE.search(text):
        return 0.0, None, _NO_ANTE.sub(" ", text)
    mode = "bb" if _BB_ANTE.search(text) or _LIVE.search(text) else None
    text = _BB_ANTE.sub(" ante ", text) if mode else text
    found = _ANTE.search(text)
    if not found:
        return None, mode, text.replace(" ante ", " ")
    value, unit = float(found.group(1)), found.group(2)
    as_percent = unit in ("%", "เปอร์เซ็นต์") or (unit is None and value >= 1 and mode is None)
    ante = value / 100 if as_percent else value
    return ante, mode or "each", text[:found.start()] + " " + text[found.end():]


def _read_payouts(text: str) -> tuple[tuple[float, ...] | None, str]:
    """(รางวัลแต่ละอันดับ, ข้อความที่ตัดรางวัลออกแล้ว) ตัดออกเพื่อไม่ให้เลขรางวัลถูกอ่านเป็นสแตก"""
    if _CHIP_EV.search(text):
        return (), _CHIP_EV.sub(" ", text)
    found = _PAYOUTS.search(text)
    if found:
        prizes = tuple(_stack_value(n) for n in re.findall(r"\d+(?:\.\d+)?", found.group(1)))
        return prizes, text[:found.start()] + " " + text[found.end():]
    return None, text


def _read_stage(text: str) -> tuple[dict, str]:
    """(ช่วงของทัวร์ที่บอกมา, ข้อความที่ตัดออกแล้ว) ไม่ให้ 120 ใน "เหลือ 120 คน" เป็นขนาดโต๊ะ"""
    found: dict = {}
    for key, pattern, read in (("left_pct", _LEFT_PCT, _stack_value), ("paid_pct", _PAID, _stack_value),
                               ("players_left", _LEFT_COUNT, int), ("entrants", _ENTRANTS, int),
                               ("field_avg", _AVERAGE, _stack_value)):
        match = pattern.search(text)
        if match:
            value = read(next(g for g in match.groups() if g is not None))
            text = text[:match.start()] + " " + text[match.end():]
            if value > 0:   # "0 left" ไม่มีความหมาย ถือว่าไม่ได้บอก
                found[key] = value
    return found, text


def _stack_value(text: str) -> float:
    """สแตกที่อ่านได้ 10 เป็น 10 ส่วน 5.5 เป็น 5.5 เลขเต็มจะได้แสดงว่า 10bb ไม่ใช่ 10.0bb"""
    value = float(text)
    return int(value) if value.is_integer() else value


def _shares(shares: dict) -> str:
    return " ".join(f"{name} {int(share * 100)}%" for name, share in sorted(
        shares.items(), key=lambda item: -item[1]))


# คำที่ใช้บนจอ แยกตามภาษาของผู้ถาม ชื่อ action เป็นอังกฤษทั้งสองภาษาเพราะคนเล่นไทยพูดแบบนี้
WORDS = {
    "TH": {"none": "ไม่อยู่ในเรนจ์", "mixed": "เล่นผสม", "page": "หน้า", "vs": "เจอ",
           "tournament": "ทัวร์นาเมนต์", "cash": "cash game"},
    "EN": {"none": "not in range", "mixed": "mixed", "page": "page", "vs": "vs",
           "tournament": "tournament", "cash": "cash game"},
}


def hand_answers(book: dict, chart: dict, hands: list[str], lang: str = "TH") -> list[str]:
    """คำตอบของแต่ละมือที่ถาม พร้อม % ของทุก action เช่น "K5s = fold 77% / call 23%"

    อ่านจากช่องในตารางตรง ๆ ไม่ต้องให้โมเดลไล่ช่วงเอง chart["names"] เปลี่ยนชื่อ action ได้
    เช่นชาร์ต push/fold เรียก raise ว่า shove
    """
    words = WORDS[lang]
    names = chart.get("names", {})
    lines = []
    for hand in hands:
        shares = hand_shares(book, chart, hand)
        if not shares:
            lines.append(f"{hand} = {words['none']}")
            continue
        lines.append(f"{hand} = " + " / ".join(f"{names.get(name, name)} {round(share * 100)}%"
                                               for name, share in shares))
    return lines


def hand_shares(book: dict, chart: dict, hand: str) -> list[tuple[str, float]]:
    """(action, ความถี่) ของมือหนึ่ง เรียงจากบ่อยสุด ว่างถ้ามือนี้ไม่อยู่ในเรนจ์"""
    action = CODE_ACTIONS.get(dict(zip(book["hand_order"], chart["actions"])).get(hand, "-"), "none")
    if action == "none":
        return []
    shares = chart.get("mixed", {}).get(hand) or {action: 1.0}
    return sorted(shares.items(), key=lambda item: -item[1])


def _score(chart: dict, request: Request) -> tuple:
    """ยิ่งน้อยยิ่งตรง ใช้เรียงหาชาร์ตที่ใกล้ที่สุด"""
    villain_miss = 0 if request.villain is None else int(chart.get("villain") != request.villain)
    scenario_miss = int(bool(request.scenario) and chart["scenario"].upper()
                        != request.scenario.upper())
    stack_gap = abs(chart["stack"] - request.stack) if request.stack else 0
    return (scenario_miss, villain_miss, stack_gap, chart["page"])


def find(question: str) -> tuple[dict, dict, Request] | None:
    """ชาร์ตที่ตรงกับคำถามที่สุด คืน (เล่ม, ชาร์ต, สิ่งที่ถอดจากคำถาม)"""
    request = parse(question)
    if not request.usable:
        return None
    best = None
    for book in books():
        if request.game and book["game"] != request.game:
            continue
        for chart in book["charts"]:
            if chart["hero"] != request.hero:
                continue
            key = _score(chart, request)
            if best is None or key < best[0]:
                best = (key, book, chart)
    if best is None:
        return None
    return best[1], best[2], request


def _collapse(pairs: list[str]) -> list[str]:
    """ย่อรายชื่อไพ่ที่ไล่ต่อกันให้เป็นช่วง เช่น TT+ หรือ 99-77"""
    if not pairs:
        return []
    ordered = sorted(pairs, key=lambda hand: STRENGTH[hand[0]])
    groups: list[list[str]] = [[ordered[0]]]
    for hand in ordered[1:]:
        if STRENGTH[hand[0]] - STRENGTH[groups[-1][-1][0]] == 1:
            groups[-1].append(hand)
            continue
        groups.append([hand])
    parts = []
    for group in groups:
        if len(group) == 1:
            parts.append(group[0])
        elif STRENGTH[group[0][0]] == 0:
            parts.append(f"{group[-1]}+")
        else:
            parts.append(f"{group[0]}-{group[-1]}")
    return parts


def _suited_group(hands: list[str], suffix: str) -> list[str]:
    """ย่อมือที่มีไพ่สูงตัวเดียวกัน เช่น A5s+ หรือ K9s-K6s"""
    parts = []
    for high in RANKS:
        lows = [hand for hand in hands if hand[0] == high and hand.endswith(suffix)]
        if not lows:
            continue
        ordered = sorted(lows, key=lambda hand: STRENGTH[hand[1]])
        groups: list[list[str]] = [[ordered[0]]]
        for hand in ordered[1:]:
            if STRENGTH[hand[1]] - STRENGTH[groups[-1][-1][1]] == 1:
                groups[-1].append(hand)
                continue
            groups.append([hand])
        for group in groups:
            top_kicker = STRENGTH[group[0][1]] == STRENGTH[high] + 1
            if len(group) == 1:
                parts.append(group[0])
            elif top_kicker:
                parts.append(f"{group[-1]}+")
            else:
                parts.append(f"{group[0]}-{group[-1]}")
    return parts


TOTAL_COMBOS = 1326


def combos(hand: str) -> int:
    """จำนวนคู่ไพ่จริงของมือ คู่มี 6 แบบ suited 4 แบบ offsuit 12 แบบ"""
    return 6 if len(hand) == 2 else 4 if hand.endswith("s") else 12


def range_share(book: dict, chart: dict, action: str) -> float:
    """สัดส่วนของมือทั้งหมดที่เล่น action นี้ นับตามคอมโบ ช่องที่เล่นผสมนับตามความถี่"""
    mixed = chart.get("mixed", {})
    total = 0.0
    for hand, code in zip(book["hand_order"], chart["actions"]):
        if hand in mixed:
            total += combos(hand) * mixed[hand].get(action, 0.0)
        elif CODE_ACTIONS.get(code) == action:
            total += combos(hand)
    return total / TOTAL_COMBOS


def notation(book: dict, chart: dict, action: str) -> str:
    """เรนจ์ของ action หนึ่งในรูปแบบที่คนเล่นอ่านออก"""
    order = book["hand_order"]
    chosen = [hand for hand, code in zip(order, chart["actions"])
              if CODE_ACTIONS.get(code) == action]
    pairs = [hand for hand in chosen if len(hand) == 2]
    suited = [hand for hand in chosen if hand.endswith("s")]
    offsuit = [hand for hand in chosen if hand.endswith("o")]
    parts = _collapse(pairs) + _suited_group(suited, "s") + _suited_group(offsuit, "o")
    return ", ".join(parts)


def mixed_note(chart: dict) -> str:
    """ช่องที่เล่นผสมหลาย action พร้อมความถี่"""
    notes = []
    for hand, shares in sorted(chart.get("mixed", {}).items()):
        notes.append(f"{hand} {_shares(shares)}")
    return ", ".join(notes)


def describe(book: dict, chart: dict, lang: str = "TH") -> str:
    """ชื่อสถานการณ์ของชาร์ตแบบอ่านออกเสียงได้"""
    words = WORDS[lang]
    facing = f" {words['vs']} {chart['villain']}" if chart.get("villain") else ""
    game = words["tournament"] if book["game"] == "tournament" else words["cash"]
    return f"{chart['hero']}{facing} · {chart['scenario']} · {chart['stack']} BB ({game})"


def _hands_only(question: str) -> str:
    """ไม่รู้ว่าสถานการณ์ไหน แต่อย่างน้อยบอกโมเดลว่ามือที่ได้ยินคือมืออะไร

    ตัวถอดเสียงเขียน สิบแปดออฟสูท เป็น 18 offsuit โมเดลอ่านแล้วงงว่ามือ 18 คืออะไร
    """
    hands = hands_in(question)
    if not hands:
        return ""
    return ("# มือที่ผู้ใช้พูดถึง (ตัวถอดเสียงอาจเขียนไพ่สิบเป็นเลข 1 เช่น 18 คือ T8)\n"
            + ", ".join(hands))


def context_block(question: str, on_screen: bool = False) -> str:
    """บล็อกบริบทสำหรับแปะเข้าพรอมต์ คืนค่าว่างถ้าไม่มีชาร์ตที่ตรง

    on_screen คือตาราง 13x13 ถูกวาดให้ผู้ใช้ดูบนจอแล้ว
    """
    found = find(question)
    if found is None:
        return _hands_only(question)
    book, chart, request = found
    lines = [
        "# ตารางพรีฟล็อป GTO (ตัวเลขจริง ใช้แทนการเดา)",
        "",
        f"## {describe(book, chart)}",
        f"ที่มา {book['title']} หน้า {chart['page']}",
    ]
    if request.stack and request.stack != chart["stack"]:
        # บอกให้รู้ว่าไม่ใช่สแตกที่ถามตรง ๆ ไม่งั้นจะอ้างตัวเลขผิดความลึก
        lines.append(f"หมายเหตุ ผู้ใช้ถามที่ {request.stack} BB "
                     f"แต่คู่มือมีใกล้สุดที่ {chart['stack']} BB "
                     f"ยิ่งสแตกสั้นกว่านี้เรนจ์ยิ่งต้องกว้างขึ้น")
    raise_means = RAISE_MEANS.get(chart["scenario"]) if chart.get("villain") else None
    if raise_means:
        # โมเดลเคยตอบว่าไม่มีเรนจ์ BB 3-bet ทั้งที่อยู่ในช่อง raise ของชาร์ต BB เจอ BTN เปิด
        lines.append(f"ช่อง raise ในตารางนี้คือเรนจ์ {raise_means} ของ {chart['hero']} "
                     f"ใส่ {chart['villain']}")
    lines.append("")
    for action in ("raise", "call"):
        hands = notation(book, chart, action)
        if hands:
            share = range_share(book, chart, action) * 100
            lines.append(f"{action} (ราว {share:.1f}% ของมือทั้งหมด): {hands}")
    mixed = mixed_note(chart)
    if mixed:
        lines.append(f"เล่นผสม: {mixed}")
    # ไม่ไล่รายชื่อมือที่ไม่อยู่ในเรนจ์ เพราะบางชาร์ตมีเป็นร้อยมือ พรอมต์จะบวมเปล่า ๆ
    if "-" in chart["actions"]:
        lines.append("มือที่ไม่อยู่ในรายการคือ fold หรือไม่ได้อยู่ในเรนจ์ที่เปิดมาตั้งแต่ต้น")
    else:
        lines.append("มือที่ไม่อยู่ในรายการข้างบนคือ fold")
    # โมเดลเคยไล่ช่วง A6o-A2o แล้วนับ A8o ว่าอยู่ในนั้น จึงเปิดตารางตอบมือที่ถามให้เสร็จ
    asked = hand_answers(book, chart, hands_in(question))
    if asked:
        lines += ["", "## มือที่ผู้ใช้ถาม (อ่านจากตารางแล้ว ใช้ตามนี้ ห้ามไล่ช่วงเอง)", *asked]
    if on_screen:
        # อ่านรายชื่อมือเป็นเสียงช้าและฟังไม่ทัน ผู้ใช้เคยบ่นว่าไล่ทีละแฮนด์ช้าตาย
        lines += ["", "## วิธีพูดเรื่องตารางนี้",
                  "ผู้ใช้เห็นตาราง 13x13 ของชาร์ตนี้บนจออยู่แล้ว ห้ามไล่รายชื่อมือหรือช่วงมือตอนพูด",
                  "ให้เล่าภาพกว้าง เช่น เปิดราวกี่เปอร์เซ็นต์ กลุ่มไหนเปิดเกือบหมด กลุ่มไหนตัดทิ้ง "
                  "แล้วชวนให้ดูตารางบนจอ",
                  "ถ้าผู้ใช้ถามมือเฉพาะ ให้ตอบมือนั้นตรง ๆ ได้"]
    return "\n".join(lines)
