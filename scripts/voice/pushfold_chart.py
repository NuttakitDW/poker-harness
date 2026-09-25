"""สแตกสั้นในทัวร์นาเมนต์ แก้ชาร์ต push/fold สด ๆ แทนการเปิดชาร์ตจากหนังสือ

ที่ 15bb ลงไป เหลือแค่สองปุ่มคือ shove กับ fold ชาร์ตหนังสือมีไม่ครบทุกสแตก
แต่ solver ใน pushfold/ แก้ได้ทุกสแตกในเวลาไม่ถึงสองวินาที
ผลออกมาในรูป book กับ chart แบบเดียวกับไฟล์ชาร์ต chart_grid จึงวาดได้เลย

สิ่งที่ผู้ใช้ไม่ได้บอก สมมติไว้แล้วพิมพ์บอกใต้ตาราง
โต๊ะ 8 คนถ้าไม่บอกขนาดโต๊ะ ทุกคนสแตกเท่ากัน ทุกคนจ่าย ante 10% ของ BB ถ้าไม่บอก ante
สแตกที่บอกคือที่เหลือหลังจ่าย ante แล้ว บอก 1.5bb กับ ante 0.1bb คือมี 1.6bb ก่อนจ่าย
บอก "bb ante" หรือ "live" คือ BB จ่าย ante แทนทั้งโต๊ะ ค่าเริ่ม 1bb บวก ante คืนให้แค่ BB
heads-up คนที่เป็น button คือ SB จึงแสดงเป็น BTN/SB
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import preflop  # noqa: E402
from pushfold import coach, floor, hands  # noqa: E402
from pushfold.spot import Spot, SpotError  # noqa: E402

MAX_STACK = 15
TABLE_SIZE = 8
DEFAULT_ANTE = {"each": 0.1, "bb": 1.0}  # เป็น bb ต่อคนที่จ่าย
FIRST_IN, FACING = "Push/Fold", "Call vs shove"
TITLE = "Push/fold Nash solver (chip EV)"
HU_BUTTON = "BTN/SB"

_LIBRARY = coach.Library()


@dataclasses.dataclass(frozen=True)
class Solved:
    book: dict
    chart: dict
    note: str


def applies(request: preflop.Request) -> bool:
    """สแตกที่ผู้ใช้บอกเองไม่เกิน 15bb หรือขอ push/fold มาตรง ๆ และไม่ใช่ cash game"""
    if request.game == "cash" or request.stack is None:
        return False
    return request.stack <= MAX_STACK or request.pushfold


def history(names: tuple[str, ...], hero: str, villain: str | None,
            shovers: tuple[str, ...] = ()) -> tuple[int, ...]:
    """action ของที่นั่งก่อนผู้ถาม ทุกคน fold ยกเว้นคนที่ shove มา (shovers หรือคู่มือคนเดียว)

    คู่มือที่นั่งหลังผู้ถามยังไม่ได้เล่น จึงถือเป็นการเล่นคนแรก
    BB ที่ไม่บอกคู่มือ ถ้าทุกคน fold มาก็ไม่มีอะไรให้ตัดสิน จึงตอบเป็น BB เจอ SB shove
    """
    seat = names.index(hero)
    if villain is None and hero == "BB":
        villain = "SB"
    jammed = set(shovers) or {villain}
    return tuple(floor.JAM if names[i] in jammed else floor.FOLD for i in range(seat))


def _seat(names: tuple[str, ...], name: str | None) -> str | None:
    """heads-up ไม่มีที่นั่ง BTN แยก button คือ SB"""
    return "SB" if len(names) == 2 and name == "BTN" else name


def _label(names: tuple[str, ...], name: str | None) -> str | None:
    return HU_BUTTON if len(names) == 2 and name == "SB" else name


def _mode(request: preflop.Request) -> str:
    return request.ante_mode or "each"


def _ante(request: preflop.Request) -> float:
    return DEFAULT_ANTE[_mode(request)] if request.ante is None else request.ante


def _spot(stack: float, players: int, ante: float, mode: str) -> Spot:
    # สแตกที่ถามไม่รวม ante จึงบวก ante กลับให้ทุกคนที่จ่าย ante ก่อนจ่าย
    payers = range(players) if mode == "each" else (players - 1,)
    stacks = tuple(round(stack + (ante if seat in payers else 0.0), 9) for seat in range(players))
    return Spot(stacks=stacks, ante=ante, ante_mode=mode)


def table(request: preflop.Request) -> Spot:
    """โต๊ะที่จะแก้สำหรับคำถามนี้"""
    return _spot(request.stack, request.players or TABLE_SIZE, _ante(request), _mode(request))


@functools.lru_cache(maxsize=64)
def _solve(stack: float, players: int, ante: float, mode: str) -> coach.Result:
    # ผลเดียวมีทุกที่นั่งทุกสถานการณ์ในโต๊ะ ถามที่นั่งอื่นในสแตกเดิมจึงไม่ต้องแก้ใหม่
    return coach.solve(_spot(stack, players, ante, mode), library=_LIBRARY)


def all_in_by_posting(request: preflop.Request) -> bool:
    """ผู้ถามจ่าย blind กับ ante แล้วหมดตัวพอดี ไม่มีอะไรให้ตัดสินใจ เช่น BB ที่เหลือไม่ถึง 1bb หลัง ante"""
    try:
        spot = table(request)
    except SpotError:
        return False
    hero = _seat(spot.names, request.hero)
    return hero in spot.names and spot.names.index(hero) in spot.forced


def _cells(frequencies, action: str, order: list[str]) -> tuple[str, dict]:
    code = "C" if action == "call" else "R"
    by_hand = dict(zip(hands.CLASSES, frequencies))
    codes, mixed = [], {}
    for hand in order:
        p = float(by_hand[hand])
        codes.append(code if p >= 0.5 else "F")
        if coach.DISPLAY_CUTOFF <= p <= 1 - coach.DISPLAY_CUTOFF:
            mixed[hand] = {action: round(p, 2), "fold": round(1 - p, 2)}
    return "".join(codes), mixed


def _ante_words(request: preflop.Request) -> str:
    if _mode(request) == "bb":
        return f"BB ante {_ante(request):g}bb"
    return f"ante {_ante(request):g}bb each"


def solved(request: preflop.Request) -> Solved | None:
    """ชาร์ตที่แก้แล้วของผู้ถาม คืน None ถ้าแก้ไม่ได้ เช่นสแตกไม่พอจ่าย blind กับ ante"""
    try:
        result = _solve(request.stack, request.players or TABLE_SIZE, _ante(request),
                        _mode(request))
    except SpotError:
        return None
    names = result.spot.names
    hero, villain = _seat(names, request.hero), _seat(names, request.villain)
    if hero not in names or names.index(hero) in result.spot.forced:
        return None
    past = history(names, hero, villain, tuple(_seat(names, s) for s in request.shovers))
    seat = names.index(hero)
    node = result.node(seat, past)
    facing = floor.JAM in past
    villain = "+".join(_label(names, names[i]) for i, act in enumerate(past) if act == floor.JAM) or None
    order = list(hands.CLASSES)  # เรียง A..2 แถวต่อแถว ตรงกับ hand_order ในไฟล์ชาร์ต
    action = "call" if facing else "raise"
    actions, mixed = _cells(result.strategy[node.index][:, floor.JAM], action, order)
    book = {"game": "tournament", "title": TITLE, "hand_order": order}
    chart = {"stack": request.stack, "section": "SOLVER", "page": None,
             "hero": _label(names, hero), "villain": villain,
             "scenario": FACING if facing else FIRST_IN, "actions": actions, "mixed": mixed,
             "names": {"raise": "shove"}}
    table = "heads-up" if len(names) == 2 else f"{len(names)}-handed"
    note = (f"push/fold Nash, {table}, all stacks {request.stack}bb after the ante, "
            f"{_ante_words(request)}, {result.range_pct(seat, past) * 100:.1f}% of hands "
            f"{'call' if facing else 'shove'}, exploitability {result.exploitability:.3f}bb, "
            f"solved in {result.seconds:.1f}s")
    if request.stack > MAX_STACK:
        # สแตกลึกกว่านี้ Nash จริงมี min-raise กับ limp ด้วย ชาร์ตนี้จึงเป็นแค่ค่าประมาณ
        note += f"; above {MAX_STACK}bb real play also min-raises, treat as approximate"
    return Solved(book, chart, note)
