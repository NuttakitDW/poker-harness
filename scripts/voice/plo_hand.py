"""อ่านมือ PLO สี่ใบจากคำถาม แล้วตัดสินด้วยวิธี miracle flop ของ Jeff Hwang

โมเดลเคยจัดระดับ JJ63 ผิดและถามตำแหน่งกลับ ทั้งที่ระดับมือไม่ขึ้นกับตำแหน่ง
จึงให้โค้ดทำส่วนที่ต้องแม่น คือหาคำตอบจากแบบฝึก และนับว่ามือนี้ติด nuts บน flop
แบบไหน บ่อยแค่ไหน ด้วยไพ่คู่ไหน แล้วส่งให้โมเดลเป็นข้อเท็จจริง ไม่ต้องเดาเอง

การนับดูแค่อันดับไพ่ ไม่นับ flush เพราะผู้ใช้มักบอกแค่ว่า double-suited ไม่บอกดอกจริง
flop ที่เป็นไปได้ทั้งหมดมีแค่ 455 แบบเมื่อไม่สนดอก จึงนับครบทุกแบบได้ในเสี้ยววินาที
"""

from __future__ import annotations

import collections
import dataclasses
import functools
import itertools
import math
import pathlib
import re

import plo_low
import retrieval

ROOT = pathlib.Path(__file__).resolve().parents[2]
DRILL_NOTES = ROOT / "harnesses" / "EN" / "sources" / "web"
DRILL_GLOB = "plo-starting-hands-classify-*.md"
_DRILL_LINE = re.compile(r"^- มือ \S+ \(([AKQJT2-9]{4}) ([a-z-]+)\) → ระดับ (\w+): (.+)$",
                         re.MULTILINE)
PREFLOP_GLOB = "plo-starting-hands-preflop-*.md"
_PREFLOP_LINE = re.compile(
    r"^- มือ \S+ \(([AKQJT2-9]{4}) ([a-z-]+)\) สถานการณ์: (.+?) → คำตอบ (\w+): (.+)$", re.MULTILINE)

RANKS = retrieval.RANK_ORDER
VALUE = {rank: 14 - index for index, rank in enumerate(RANKS)}
LETTER = {value: rank for rank, value in VALUE.items()}
DECK_COPIES = 4
UNSEEN_CARDS = 48
ALL_FLOPS = math.comb(UNSEEN_CARDS, 3)
WHEEL = (14, 5, 4, 3, 2)
# window ของ straight จากใหญ่ไปเล็ก A-K-Q-J-T ถึง 5-4-3-2-A
STRAIGHT_WINDOWS = tuple(frozenset(range(high - 4, high + 1)) for high in range(14, 5, -1)) \
    + (frozenset(WHEEL),)
# open-ender มี 8 outs, wrap ใหญ่ 13 outs ขึ้นไป
DRAW_OUTS = 8
WRAP_OUTS = 13

# อันดับมือแบบไม่มี flush
HIGH, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FULL_HOUSE, QUADS = range(7)
HILO_HEADING = "# มือ PLO Hi/Lo ที่ถาม (โค้ดคำนวณให้ ใช้ข้อเท็จจริงนี้แทนการเดา)"
KINDS = ("straight", "set", "full house ขึ้นไป", "อื่น ๆ")
# มือที่ไม่มีไพ่สามใบอยู่ใน straight เดียวกันคือ Hold'em สองมือแยกกัน อย่าง Q-J-7-6 ในแบบฝึก
SPLIT_MAX_LINKED = 2
SPLIT_TWIN = "QJ76"

SHAPES = (
    ("double-suited", ("ดับเบิล", "ดับเบิ้ล", "double", "ds")),
    ("single-suited", ("ซิงเกิล", "ซิงเกิ้ล", "single", "ss")),
    ("rainbow", ("เรนโบว์", "เรนโบ", "rainbow", "ไม่มีดอกซ้ำ")),
    # "ซูต" เฉย ๆ อย่าง "A 2 ซูต" คือมีดอกซ้ำหนึ่งชุด ตรวจหลังคำ double จึงไม่ชนกับ "ดับเบิลซูต"
    ("single-suited", ("ซูต", "สูท", "suited")),
)

# ชื่อดอกที่ถอดจากเสียง คำยาวต้องมาก่อน "จิก" จะได้ไม่นับ "ดอกจิก" ซ้ำสองครั้ง
SUIT_WORDS = (
    ("spades", ("โพดำ", "พอดำ", "สเปด", "spade", "spades")),
    ("hearts", ("โพแดง", "ฮาร์ท", "heart", "hearts")),
    ("diamonds", ("ข้าวหลามตัด", "ไดมอนด์", "diamond", "diamonds")),
    ("clubs", ("ดอกจิก", "จิก", "คลับ", "club", "clubs")),
)
_SUIT_WORD = re.compile(
    "(" + "|".join(sorted((re.escape(word) for _, words in SUIT_WORDS for word in words),
                          key=len, reverse=True)) + r")(\s*2\s*ใบ)?")
_CLAUSE = re.compile(r"[,.;]|ส่วน|แล้วก็|และ(?!กัน)")


@dataclasses.dataclass(frozen=True)
class Drill:
    """คำตอบจัดระดับมือหนึ่งข้อจากแบบฝึก"""

    hand: str
    shape: str
    tier: str
    reason: str


@dataclasses.dataclass(frozen=True)
class Study:
    """ผลนับ miracle flop ของมือหนึ่ง อัตราเป็นสัดส่วนของ flop ทั้งหมด"""

    hand: str
    nut_rate: float
    rates: dict[str, float]
    examples: dict[str, str]
    working: dict[str, float]
    # flop ที่ยังไม่ได้ nuts แต่มี nut straight draw ตั้งแต่ open-ender และตั้งแต่ wrap ใหญ่
    draw_rate: float = 0.0
    wrap_rate: float = 0.0
    wrap_example: str = ""


def _suit_counts(text: str) -> collections.Counter:
    """จำนวนใบของแต่ละดอกที่พูดถึง "ดอกจิก 2 ใบ" นับเป็นสองใบ"""
    counts: collections.Counter = collections.Counter()
    for match in _SUIT_WORD.finditer(text.replace("ํา", "ำ").lower()):
        suit = next(name for name, words in SUIT_WORDS if match.group(1) in words)
        counts[suit] += 2 if match.group(2) else 1
    return counts


def _named_suits(text: str) -> str | None:
    """นับดอกที่บอกทีละใบ เช่น "A โพดำ 2 โพดำ" หรือ "ดอกจิก 2 ใบ" ดอกที่ซ้ำหนึ่งชุดคือ single-suited"""
    counts = _suit_counts(text)
    repeated = sum(1 for count in counts.values() if count >= 2)
    return {0: None, 1: "single-suited"}.get(repeated, "double-suited")


def shape(text: str) -> str | None:
    """ลักษณะดอกที่พูดถึง เช่น double-suited หรือ None ถ้าไม่ได้บอก"""
    lowered = text.lower()
    for name, words in SHAPES:
        if any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered) for word in words):
            return name
    return _named_suits(text)


@functools.lru_cache(maxsize=1)
def _drills() -> tuple[Drill, ...]:
    found: list[Drill] = []
    for path in sorted(DRILL_NOTES.glob(DRILL_GLOB)):
        for hand, form, tier, reason in _DRILL_LINE.findall(path.read_text(encoding="utf-8")):
            found.append(Drill(hand, form, tier, reason.strip()))
    return tuple(found)


@dataclasses.dataclass(frozen=True)
class Spot:
    """คำตอบตัดสินใจ preflop หนึ่งข้อจากแบบฝึก มือเดียวกันมีได้หลายสถานการณ์"""

    hand: str
    shape: str
    situation: str
    action: str
    reason: str


@functools.lru_cache(maxsize=1)
def _spots() -> tuple[Spot, ...]:
    found: list[Spot] = []
    for path in sorted(DRILL_NOTES.glob(PREFLOP_GLOB)):
        for hand, form, situation, action, reason in _PREFLOP_LINE.findall(
                path.read_text(encoding="utf-8")):
            found.append(Spot(hand, form, situation.strip(), action, reason.strip()))
    return tuple(found)


def spots(hand: str) -> tuple[Spot, ...]:
    """ข้อในแบบฝึก preflop ที่เป็นมือนี้"""
    return tuple(item for item in _spots() if item.hand == hand)


def drill(hand: str, form: str | None = None) -> Drill | None:
    """ข้อในแบบฝึกที่ตรงมือนี้ ถ้าบอกดอกมาด้วยให้ข้อที่ดอกตรงกันขึ้นก่อน"""
    matches = [item for item in _drills() if item.hand == hand]
    exact = [item for item in matches if item.shape == form]
    return (exact or matches or [None])[0]


def _score(cards: tuple[int, ...]) -> tuple:
    """ความแรงของไพ่ห้าใบแบบไม่นับ flush เปรียบเทียบกันได้ตรง ๆ"""
    counts = collections.Counter(cards)
    grouped = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    shape_ = tuple(count for _, count in grouped)
    order = tuple(value for value, _ in grouped)
    distinct = sorted(counts, reverse=True)
    if len(distinct) == 5 and (distinct[0] - distinct[4] == 4 or tuple(distinct) == WHEEL):
        return (STRAIGHT, 5 if tuple(distinct) == WHEEL else distinct[0])
    category = {(4, 1): QUADS, (3, 2): FULL_HOUSE, (3, 1, 1): TRIPS,
                (2, 2, 1): TWO_PAIR, (2, 1, 1, 1): PAIR}.get(shape_, HIGH)
    return (category, *order)


def _best(hole: tuple[int, ...], board: tuple[int, ...]) -> tuple[tuple, tuple[int, int]]:
    """มือที่ดีที่สุดเมื่อใช้ไพ่ในมือสองใบพอดี พร้อมไพ่คู่ที่ใช้"""
    return max((_score(pair + board), pair) for pair in itertools.combinations(hole, 2))


def _kind(score: tuple, pair: tuple[int, int]) -> str:
    if score[0] >= FULL_HOUSE:
        return KINDS[2]
    if score[0] == STRAIGHT:
        return KINDS[0]
    if score[0] == TRIPS and pair[0] == pair[1]:
        return KINDS[1]
    return KINDS[3]


def _nuts(board: tuple[int, ...], left: collections.Counter) -> tuple:
    """มือที่ดีที่สุดที่คนอื่นถือได้ จากไพ่ที่ยังเหลือ"""
    ranks = [value for value in left if left[value]]
    pairs = [(a, b) for a, b in itertools.combinations_with_replacement(ranks, 2)
             if a != b or left[a] >= 2]
    return max(_score(pair + board) for pair in pairs)


def _nut_straight(hole: tuple[int, ...], board: tuple[int, ...]) -> bool:
    """บน board ห้าใบที่ไม่มีคู่ มือนี้ถือ straight ที่ใหญ่ที่สุดที่ board ยอมให้ทำได้ไหม

    board ไม่มีคู่และไม่นับ flush ของที่ใหญ่สุดจึงเป็น straight ถ้ามี window ไหนมีไพ่ board ถึงสามใบ
    """
    ranks = set(board)
    for window in STRAIGHT_WINDOWS:
        if len(window & ranks) < 3:
            continue
        return any(len({a, b}) == 2 and {a, b} <= window and window - {a, b} <= ranks
                   for a, b in itertools.combinations(hole, 2))
    return False


def _nut_outs(hole: tuple[int, ...], flop: tuple[int, ...], left: collections.Counter) -> int:
    """จำนวนไพ่ turn ที่ทำให้ได้ nut straight"""
    return sum(left[turn] for turn in left
               if left[turn] and turn not in flop and _nut_straight(hole, (*flop, turn)))


def _linked(hand: str) -> int:
    """จำนวนไพ่ต่างอันดับที่มากที่สุดซึ่งอยู่ใน straight เดียวกันได้"""
    values = {VALUE[rank] for rank in hand}
    return max(len(values & window) for window in STRAIGHT_WINDOWS)


def split_hand(hand: str) -> bool:
    """มือที่แตกเป็น Hold'em สองมือ ไม่มีคู่ ไม่มี A และไม่มีสามใบต่อกันเป็น straight ได้

    A หรือคู่ยังมีทาง nut flush หรือ set จึงไม่ตัดสินว่าเป็น Trash ให้
    """
    return (len(set(hand)) == len(hand) and "A" not in hand
            and _linked(hand) <= SPLIT_MAX_LINKED)


def _label(values: tuple[int, ...]) -> str:
    return "-".join(LETTER[value] for value in sorted(values, reverse=True))


@functools.lru_cache(maxsize=64)
def study(hand: str) -> Study:
    """นับทุก flop ว่ามือนี้ติด nuts ทันทีบ่อยแค่ไหน แบบไหน และด้วยไพ่คู่ไหน"""
    hole = tuple(VALUE[rank] for rank in hand)
    unseen = collections.Counter({value: DECK_COPIES for value in VALUE.values()})
    unseen.subtract(hole)
    rates: dict[str, float] = dict.fromkeys(KINDS, 0.0)
    examples: dict[str, str] = {}
    working: collections.Counter = collections.Counter()
    draws = [0.0, 0.0]
    wrap_example = ""
    # ไล่ flop จากไพ่ใหญ่ลงเล็ก ตัวอย่างแรกที่เจอจึงเป็น flop ที่ไม่ซ้ำไพ่ในมือและสูงที่สุด
    flops = sorted(itertools.combinations_with_replacement(sorted(VALUE.values(), reverse=True), 3),
                   key=lambda flop: (len(set(flop) & set(hole)), len(set(flop)) < 3,
                                     [-value for value in flop]))
    for board in flops:
        needed = collections.Counter(board)
        weight = math.prod(math.comb(unseen[value], count) for value, count in needed.items())
        if not weight:
            continue
        left = unseen - needed
        share = weight / ALL_FLOPS
        score, pair = _best(hole, board)
        if score < _nuts(board, left):
            if len(needed) == 3:
                outs = _nut_outs(hole, board, left)
                draws[0] += share * (outs >= DRAW_OUTS)
                draws[1] += share * (outs >= WRAP_OUTS)
                if outs >= WRAP_OUTS and not wrap_example:
                    wrap_example = f"{_label(board)} ({outs} outs)"
            continue
        kind = _kind(score, pair)
        rates[kind] += share
        # คั่นขีดไว้ ไม่งั้นโมเดลเขียน 65 แล้วเครื่องอ่านว่าหกสิบห้า
        working[f"{LETTER[pair[0]]}-{LETTER[pair[1]]}"] += share
        examples.setdefault(kind, _label(board))
    return Study(hand, sum(rates.values()), rates, examples, dict(working),
                 draws[0], draws[1], wrap_example)


def _percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def _study_lines(result: Study) -> list[str]:
    lines = [f"- flop ที่ติด nuts ทันที: {_percent(result.nut_rate)} ของ flop ทั้งหมด"]
    for kind in KINDS:
        if result.rates[kind]:
            example = result.examples.get(kind)
            detail = f" เช่น flop {example}" if example and kind != KINDS[3] else ""
            lines.append(f"  - {kind}: {_percent(result.rates[kind])}{detail}")
    lines.append(f"- flop ที่ได้ nut straight draw {DRAW_OUTS} outs ขึ้นไป: {_percent(result.draw_rate)}")
    if result.wrap_rate:
        lines.append(f"  - wrap {WRAP_OUTS} outs ขึ้นไป: {_percent(result.wrap_rate)} เช่น flop {result.wrap_example}")
    lines.append(f"- รวมติด nuts หรือได้ draw ไป nuts: {_percent(result.nut_rate + result.draw_rate)}")
    used = sorted(result.working.items(), key=lambda item: item[1], reverse=True)
    if used:
        lines.append("- ไพ่คู่ที่พาไปถึง nuts: " + ", ".join(
            f"{pair} {share / result.nut_rate * 100:.0f}%" for pair, share in used[:4]))
    idle = [rank for rank in dict.fromkeys(result.hand)
            if not any(rank in pair for pair in result.working)]
    if idle:
        lines.append(f"- ไพ่ที่ไม่เคยช่วยทำ nuts: {' '.join(idle)} (dangler)")
    return lines


def suited_ace(text: str) -> bool:
    """ผู้ใช้บอกว่า A อยู่ในดอกที่ซ้ำไหม เช่น "โพดำ 2 ใบคือ A กับ 2" หรือ "A โพดำ 2 โพดำ"

    ดูทีละท่อนที่คั่นด้วยจุลภาคหรือคำอย่าง "ส่วน" ท่อนที่พูดถึงดอกและมี A ด้วยถือว่า A มีดอกคู่
    """
    if shape(text) not in ("single-suited", "double-suited"):
        return False
    counts = _suit_counts(text)
    latin = retrieval.latin_ranks(text.replace("ํา", "ำ"))
    for clause in _CLAUSE.split(latin):
        # ดอกในท่อนนี้ต้องเป็นดอกที่ซ้ำ "A เป็นไดมอนด์" ใบเดียวไม่ใช่ suited ace
        repeated = any(counts[suit] >= 2 for suit in _suit_counts(clause))
        if (repeated or re.search(r"ซูต|สูท|suited", clause, re.IGNORECASE)) and \
                re.search(r"(?<![A-Za-z])A(?![A-Za-z])", clause):
            return True
    return False


def _suit_note(hand: str, form: str | None, ace_suited: bool = False) -> str:
    if form == "rainbow":
        return "- rainbow ไม่มี flush draw เลย"
    if "A" not in hand:
        return "- ไม่มี A ถ้ามีดอกคู่ flush ที่ทำได้ไม่ใช่ nut flush เสมอไป"
    if ace_suited:
        return "- A มีดอกคู่ (suited ace) ได้ nut flush draw ช่วยอีกทาง"
    return "- ยังไม่รู้ว่า A มีดอกคู่ไหม ถ้ามี จะได้ nut flush draw ช่วยอีกทาง"


def context_block(question: str, earlier: str = "", hilo: bool = False) -> str:
    """ข้อเท็จจริงของมือ PLO ที่ถาม ส่งให้โมเดลก่อนเอกสารอื่น

    มือในคำถามล่าสุดชนะมือจากตาก่อน ส่วนคำถามสั้นอย่าง "ดับเบิลซูต" ยืมมือจากตาก่อน
    เกม Hi/Lo ใช้ระดับจากแบบฝึก PLO high ไม่ได้ จึงส่งข้อเท็จจริงฝั่ง low แทน
    """
    found = retrieval.hands(question) or retrieval.hands(earlier)
    if not found:
        return ""
    hand = found[0]
    form = shape(question) or (shape(earlier) if not retrieval.hands(question) else None)
    ace_suited = suited_ace(question if retrieval.hands(question) else earlier)
    if hilo:
        return _hilo_block(hand, form, ace_suited)
    lines = [
        "# มือ PLO ที่ถาม (โค้ดคำนวณให้ ใช้ตัวเลขนี้แทนการเดา)",
        f"มือ {'-'.join(hand)} ดอก: {form or 'ไม่ได้บอก'}",
        "ไพ่ในมือมีแค่สี่ใบนี้ ตัวเลขอื่นในคำถามเป็นเสียงที่ถอดเพี้ยน ห้ามพูดถึงเป็นไพ่",
        "ระดับมือ Premium Speculative Marginal Trash ไม่ขึ้นกับตำแหน่งหรือ stack ห้ามถามตำแหน่งตอนจัดระดับ",
    ]
    answer = drill(hand, form)
    if answer:
        same = form in (None, answer.shape)
        lines.append(f"ระดับที่ถูก: {'-'.join(answer.hand)} {answer.shape} → {answer.tier} เหตุผล: {answer.reason}")
        if not same:
            lines.append(f"ระดับนี้เป็นของแบบ {answer.shape} ถ้าดอกต่างจากนี้ ให้บอกว่าขยับขึ้นหรือลงเพราะอะไร")
    else:
        lines.append("ไม่มีมือนี้ในแบบฝึก ให้จัดระดับจาก miracle flop ข้างล่างและหลักสี่ระดับ แล้วบอกว่าประยุกต์จากหลัก")
        lines.append("ห้ามลอกระดับหรือเหตุผลของมืออื่นที่คุยไปก่อนหน้า ไพ่ต่างกันใบเดียวระดับก็เปลี่ยนได้")
        twin = drill(SPLIT_TWIN)
        if split_hand(hand) and twin:
            lines.append(f"โครงสร้าง: Hold'em สองมือแยกกัน ไม่มีไพ่สามใบอยู่ใน straight เดียวกันเลย "
                         f"แบบเดียวกับ {'-'.join(twin.hand)} ที่แบบฝึกจัดเป็น {twin.tier}")
            lines.append(f"ระดับที่ควรเป็น: {twin.tier} ถึงเป็น double-suited ก็ช่วยไม่มาก เพราะไม่มี A flush ที่ได้จึงไม่ใช่ nut flush เสมอไป")
    lines.extend(_spot_lines(hand, form))
    lines.append("miracle flop (นับจากอันดับไพ่ ไม่นับ flush):")
    lines.extend(_study_lines(study(hand)))
    lines.append(_suit_note(hand, form, ace_suited))
    return "\n".join(lines)


def _spot_lines(hand: str, form: str | None) -> list[str]:
    """คำตอบ preflop จากแบบฝึกของมือนี้ ยึดคำตอบนี้ก่อนการเดาจาก miracle flop"""
    found = spots(hand)
    if not found:
        return []
    lines = ["แบบฝึก preflop ของมือนี้ (ยึดคำตอบนี้ถ้าสถานการณ์ตรงกัน ห้ามแนะนำสวนทาง):"]
    lines.extend(f"- {'-'.join(item.hand)} {item.shape} {item.situation} → {item.action}: {item.reason}"
                 for item in found)
    if form not in (None, *(item.shape for item in found)):
        lines.append(f"คำตอบนี้เป็นของแบบ {found[0].shape} ดอกที่ถามต่างไป ให้บอกว่าต่างกันอย่างไร")
    return lines


def _hilo_block(hand: str, form: str | None, ace_suited: bool) -> str:
    """ข้อเท็จจริงของมือใน PLO Hi/Lo ทั้งฝั่ง low และฝั่ง high"""
    result = study(hand)
    lines = [
        HILO_HEADING,
        f"มือ {'-'.join(hand)} ดอก: {form or 'ไม่ได้บอก'}",
        "ระดับจากแบบฝึก PLO high ใช้กับ Hi/Lo ตรง ๆ ไม่ได้ ตัดสินจากศักยภาพสองทางและโอกาส scoop",
        *plo_low.block_lines(hand),
        f"- ฝั่ง high: flop ที่ติด nuts ทันที {_percent(result.nut_rate)} (ไม่นับ flush)",
        _suit_note(hand, form, ace_suited),
    ]
    return "\n".join(lines)
