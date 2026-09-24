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
    "sb": "SB", "smallblind": "SB", "สมอลบลายด์": "SB",
    "bb": "BB", "bigblind": "BB", "บิ๊กบลายด์": "BB",
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
_OPENS = re.compile(r"\s*(?:เปิด|open|raise\s*first|rfi)")
_THREE_BETS = re.compile(r"\s*(?:3\s*-?\s*bet|three\s*bet|ทรีเบ็ท|สามเบ็ท)")
# "โดน 3-bet" หรือ "โดน BB 3-bet" แปลว่าคนถามคือคนเปิดที่ถูก 3-bet กลับ
_FACING_THREE_BET = re.compile(r"(?:โดน|เจอ).{0,15}?(?:3bet|threebet|ทรีเบ็ท|สามเบ็ท)")

# ตัวถอดเสียงเขียนบิ๊กบลายด์ได้หลายแบบ เช่น บิ๊กบาย บิกบลาย จึงจับแค่ต้นคำ
_STACK = re.compile(r"(\d{1,3})\s*(?:bb|big\s*blind|บีบี|บิ๊?กบ(?:ลาย|าย)(?:ด์|ส์)?)",
                    re.IGNORECASE)

# คำบอกว่าดอกเดียวกันหรือต่างดอก ตัวถอดเสียงเขียนได้ทั้งอังกฤษและไทย
_SUIT_WORD = r"(?i:offsuit|off-suit|suited|ออฟสูท|ออฟ|สูท)"
# คนไทยอ่าน T ว่าสิบ พูด T8 ว่าสิบแปดแล้วตัวถอดเสียงเขียนเป็น 18 ถือเป็นมือเฉพาะเมื่อตามด้วยคำบอกดอก
_TEEN_HAND = re.compile(rf"(?<!\d)1([2-9])(?=\s*{_SUIT_WORD})")
_TEN = re.compile(r"(?<!\d)10(?!\d)")
# ตัวอักษรไพ่ต้องเป็นตัวใหญ่ ไม่งั้นคำอังกฤษอย่าง at จะกลายเป็นมือ AT
_HAND = re.compile(rf"(?<![A-Za-z0-9])([AKQJT2-9])\s?([AKQJT2-9])"
                   rf"(?:\s*({_SUIT_WORD})|([so]))?(?![A-Za-z0-9])")


@dataclasses.dataclass(frozen=True)
class Request:
    """สิ่งที่ถอดได้จากคำถามว่าผู้ใช้ถามถึงสถานการณ์ไหน"""

    game: str | None = None
    stack: int | None = None
    hero: str | None = None
    villain: str | None = None
    scenario: str | None = None

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
    if len(found) < 2 or opener is None or scenario not in (None, "RFI", "3-Bet"):
        return hero, villain, scenario
    raiser = _seat_doing(text, mentions, _THREE_BETS)
    other = raiser if raiser not in (None, opener) else next(
        name for name in found if name != opener)
    if _FACING_THREE_BET.search(_squash(text)):
        return opener, other, "3-Bet"
    return other, opener, "RFI"


def _squash(text: str) -> str:
    return re.sub(r"[\s\-]+", "", text)


def _spaced_blinds(text: str) -> str:
    """ตัวถอดเสียงเขียน big blind แยกสองคำ รวมให้เป็นคำเดียวกับที่ตารางคำรู้จัก"""
    return re.sub(r"\b(big|small)[\s\-]+blind", r"\1blind", text)


def parse(question: str) -> Request:
    """อ่านคำถามแล้วเดาว่าเป็นสถานการณ์ไหน"""
    lowered = question.lower()
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
    if "vs" in lowered or "เจอ" in lowered or "โดน" in lowered:
        scenario = scenario or "RFI"
    # ถือมืออยู่ตำแหน่งเดียวโดยไม่มีใครเปิดมาก่อน คือถามว่าควรเปิดมือนี้ไหม
    # มือคู่ตัวเลขอย่าง 33 ไม่ถูกนับเป็นมือเพราะชนกับเปอร์เซ็นต์ จึงดูคำว่าถือด้วย
    asks_open = (any(word in lowered for word in (*CHART_WORDS, *HOLD_WORDS))
                 or bool(hands_in(question)))
    if hero and not villain and asks_open:
        scenario = scenario or "RFI"
    return Request(game=game, stack=int(stack.group(1)) if stack else None,
                   hero=hero, villain=villain, scenario=scenario)


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
    text = _TEN.sub("T", _TEEN_HAND.sub(r"T\1", text))
    found: list[str] = []
    for match in _HAND.finditer(text):
        first, second, word, letter = match.groups()
        suit = letter
        if word:
            suit = "o" if "off" in word.lower() or "ออฟ" in word else "s"
        # ตัวเลขล้วนไม่มีคำบอกดอก เช่น 98 เปอร์เซ็นต์ ไม่ใช่มือ
        if suit is None and first.isdigit() and second.isdigit():
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


def _shares(shares: dict) -> str:
    return " ".join(f"{name} {int(share * 100)}%" for name, share in sorted(
        shares.items(), key=lambda item: -item[1]))


def hand_answers(book: dict, chart: dict, hands: list[str]) -> list[str]:
    """คำตอบของแต่ละมือที่ถาม อ่านจากช่องในตารางตรง ๆ ไม่ต้องให้โมเดลไล่ช่วงเอง"""
    codes = dict(zip(book["hand_order"], chart["actions"]))
    mixed = chart.get("mixed", {})
    lines = []
    for hand in hands:
        action = CODE_ACTIONS.get(codes.get(hand, "-"), "none")
        answer = "ไม่อยู่ในเรนจ์" if action == "none" else action
        if hand in mixed:
            answer = f"{answer} (เล่นผสม {_shares(mixed[hand])})"
        lines.append(f"{hand} = {answer}")
    return lines


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


def describe(book: dict, chart: dict) -> str:
    """ชื่อสถานการณ์ของชาร์ตแบบอ่านออกเสียงได้"""
    facing = f" เจอ {chart['villain']}" if chart.get("villain") else ""
    game = "ทัวร์นาเมนต์" if book["game"] == "tournament" else "cash game"
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
