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
CASH_WORDS = ("cash", "แคช", "เงินสด", "ring", "ริงเกม", "zoom")

_STACK = re.compile(r"(\d{1,3})\s*(?:bb|big\s*blind|บีบี|บิ๊กบลายด์|บิกบลายด์)", re.IGNORECASE)


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


def _positions(text: str) -> list[str]:
    """ตำแหน่งที่ถูกพูดถึง เรียงตามลำดับที่โผล่ในข้อความ

    ภาษาไทยไม่เว้นวรรคระหว่างคำ จึงหาคำไทยแบบข้อความย่อย ส่วนคำอังกฤษต้องเป็นคำเต็ม
    ไม่งั้น co ในคำอื่นจะถูกอ่านเป็นตำแหน่ง cutoff
    """
    found: list[tuple[int, str]] = []
    for word, name in POSITION_WORDS.items():
        if word.isascii():
            match = re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9+])", text)
            index = match.start() if match else -1
        else:
            index = text.find(word)
        if index >= 0:
            found.append((index, name))
    ordered: list[str] = []
    for _, name in sorted(found):
        if name not in ordered:
            ordered.append(name)
    return ordered


def parse(question: str) -> Request:
    """อ่านคำถามแล้วเดาว่าเป็นสถานการณ์ไหน"""
    lowered = question.lower()
    stack = _STACK.search(lowered)

    game = None
    if any(word in lowered for word in TOURNAMENT_WORDS):
        game = "tournament"
    elif any(word in lowered for word in CASH_WORDS):
        game = "cash"

    scenario = next((name for name, words in SCENARIO_WORDS
                     if any(word in lowered for word in words)), None)

    # ตัด "80BB" ออกก่อนหาตำแหน่ง ไม่งั้น BB ที่หมายถึงหน่วยชิปจะถูกอ่านเป็นตำแหน่ง
    found = _positions(_STACK.sub(" ", lowered))
    hero = found[0] if found else None
    villain = found[1] if len(found) > 1 else None
    if "vs" in lowered or "เจอ" in lowered or "โดน" in lowered:
        scenario = scenario or "RFI"
    return Request(game=game, stack=int(stack.group(1)) if stack else None,
                   hero=hero, villain=villain, scenario=scenario)


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
        inner = " ".join(f"{name} {int(share * 100)}%" for name, share in sorted(
            shares.items(), key=lambda item: -item[1]))
        notes.append(f"{hand} {inner}")
    return ", ".join(notes)


def describe(book: dict, chart: dict) -> str:
    """ชื่อสถานการณ์ของชาร์ตแบบอ่านออกเสียงได้"""
    facing = f" เจอ {chart['villain']}" if chart.get("villain") else ""
    game = "ทัวร์นาเมนต์" if book["game"] == "tournament" else "cash game"
    return f"{chart['hero']}{facing} · {chart['scenario']} · {chart['stack']} BB ({game})"


def context_block(question: str) -> str:
    """บล็อกบริบทสำหรับแปะเข้าพรอมต์ คืนค่าว่างถ้าไม่มีชาร์ตที่ตรง"""
    found = find(question)
    if found is None:
        return ""
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
    lines.append("")
    for action in ("raise", "call"):
        hands = notation(book, chart, action)
        if hands:
            lines.append(f"{action}: {hands}")
    mixed = mixed_note(chart)
    if mixed:
        lines.append(f"เล่นผสม: {mixed}")
    # ไม่ไล่รายชื่อมือที่ไม่อยู่ในเรนจ์ เพราะบางชาร์ตมีเป็นร้อยมือ พรอมต์จะบวมเปล่า ๆ
    if "-" in chart["actions"]:
        lines.append("มือที่ไม่อยู่ในรายการคือ fold หรือไม่ได้อยู่ในเรนจ์ที่เปิดมาตั้งแต่ต้น")
    else:
        lines.append("มือที่ไม่อยู่ในรายการข้างบนคือ fold")
    return "\n".join(lines)
