"""สแตกสั้นในทัวร์นาเมนต์ แก้ชาร์ต push/fold สด ๆ แทนการเปิดชาร์ตจากหนังสือ

ที่ 15bb ลงไป เหลือแค่สองปุ่มคือ shove กับ fold ชาร์ตหนังสือมีไม่ครบทุกสแตก
แต่ solver ใน pushfold/ แก้ได้ทุกสแตกในเวลาไม่ถึงสองวินาที
ผลออกมาในรูป book กับ chart แบบเดียวกับไฟล์ชาร์ต chart_grid จึงวาดได้เลย

สิ่งที่ผู้ใช้ไม่ได้บอก สมมติไว้แล้วพิมพ์บอกใต้ตาราง
โต๊ะ 8 คนถ้าไม่บอกขนาดโต๊ะ ทุกคนสแตกเท่ากัน ทุกคนจ่าย ante 10% ของ BB ถ้าไม่บอก ante
สแตกที่บอกคือที่เหลือหลังจ่าย ante แล้ว บอก 1.5bb กับ ante 0.1bb คือมี 1.6bb ก่อนจ่าย
บอก "bb ante" หรือ "live" คือ BB จ่าย ante แทนทั้งโต๊ะ ค่าเริ่ม 1bb บวก ante คืนให้แค่ BB
heads-up คนที่เป็น button คือ SB จึงแสดงเป็น BTN/SB
บอกรางวัลมา (icm 50/30/20) แก้แบบ ICM แทน chip EV ทุกคนที่โต๊ะคือผู้เล่นที่เหลือทั้งหมด
พูด icm เฉย ๆ คือ bubble ของเกม live คนลง 20 ซื้อเข้า 500 บาท รางวัลตามตาราง structures.LIVE
บอก buy-in หรือเงินรางวัลรวม (pool) รางวัลคิดจากเงินจริง ไม่บอกคนลงก็หารเอาจาก pool ÷ buy-in
บอก aof หรือ all-in or fold คือเกม cash ของ GGPoker สเตกต่ำสุด $0.05/$0.10 Hold'em
ไม่บอกขนาดโต๊ะหรือสแตกใช้ 4 คน 10bb ไม่มี ante ทุกคนที่ถึง showdown เสียค่าธรรมเนียม 0.2bb นอกพอต
ตัวเลขจาก ggpoker.com/poker-games/all-in-or-fold ตรวจ 2026-09-26 (harness หัวข้อ 29)
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import preflop  # noqa: E402
from pushfold import coach, floor, hands, icm, structures  # noqa: E402
from pushfold.spot import MAX_PLAYERS, Spot, SpotError  # noqa: E402

MAX_STACK = 15
MAX_PRIZES_SHOWN = 9
TABLE_SIZE = 8
DEFAULT_ANTE = {"each": 0.1, "bb": 1.0}  # เป็น bb ต่อคนที่จ่าย
FIRST_IN, FACING = "Push/Fold", "Call vs shove"
TITLE = "Push/fold Nash solver ({model})"
HU_BUTTON = "BTN/SB"
# GGPoker All-in or Fold Hold'em $0.05/$0.10 ซื้อเข้า $1 = 10bb โต๊ะ 4 คน ไม่มี ante
# ค่าธรรมเนียมไม่หักจากพอตและไม่ขึ้นในประวัติมือ rake 0.06bb + jackpot 0.07bb + All-In Fortune $0.007
# สมมติว่าเก็บเฉพาะคนที่ถึง showdown fold หรือ shove แล้วทุกคน fold ไม่เสีย
AOF_STACK, AOF_PLAYERS = 10, 4
AOF_FEE = round(0.06 + 0.07 + 0.007 / 0.10, 9)
AOF_TITLE = "GGPoker All-in or Fold $0.05/$0.10 ({model})"

_LIBRARY = coach.Library()


@dataclasses.dataclass(frozen=True)
class Solved:
    book: dict
    chart: dict
    note: str


def applies(request: preflop.Request) -> bool:
    """สแตกที่ผู้ใช้บอกเองไม่เกิน 15bb หรือขอ push/fold มาตรง ๆ และไม่ใช่ cash game"""
    if request.aof:
        return True
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
    if request.ante is None and request.aof and request.ante_mode is None:
        return 0.0
    return DEFAULT_ANTE[_mode(request)] if request.ante is None else request.ante


def _stack(request: preflop.Request) -> float | None:
    return request.stack or (AOF_STACK if request.aof else None)


def _fee(request: preflop.Request) -> float:
    return AOF_FEE if request.aof else 0.0


def _spot(stack: float, players: int, ante: float, mode: str, fee: float = 0.0) -> Spot:
    # สแตกที่ถามไม่รวม ante จึงบวก ante กลับให้ทุกคนที่จ่าย ante ก่อนจ่าย
    payers = range(players) if mode == "each" else (players - 1,)
    stacks = tuple(round(stack + (ante if seat in payers else 0.0), 9) for seat in range(players))
    return Spot(stacks=stacks, ante=ante, ante_mode=mode, fee=fee)


def table(request: preflop.Request) -> Spot:
    """โต๊ะที่จะแก้สำหรับคำถามนี้"""
    return _spot(_stack(request), _players(request), _ante(request), _mode(request), _fee(request))


def _players(request: preflop.Request) -> int:
    """คนที่โต๊ะ ไม่บอกคือ 8 คน (AoF 4 คน) หรือน้อยกว่าถ้าทั้งทัวร์เหลือไม่ถึง เช่น bubble ของ SNG 50/30/20"""
    if request.players:
        return request.players
    if request.aof:
        return AOF_PLAYERS
    found = stage(request)
    return min(TABLE_SIZE, found.left) if found else TABLE_SIZE


def stage(request: preflop.Request) -> structures.Stage | None:
    """ช่วงของทัวร์ที่ผู้ถามบอก None ถ้าไม่ได้บอกว่าเหลือกี่คนและไม่ได้พูด icm เฉย ๆ

    ไม่บอกคนลงถือว่าเกม live 20 คน รางวัลตามตาราง live ถ้าเหลือมากกว่านั้น หรือคนนั่งโต๊ะนี้มากกว่าคนที่เหลือ
    ใน bubble ของเกม live ถือว่า 1000 จ่าย 15% บอกจำนวนคนได้เงินมาแต่ไม่บอกคนลง ถือว่าจ่าย 15%
    จำนวนคนที่บอกมาชนะชื่อช่วง bubble คือเกือบถึงเงิน "อีก 3 คน" คือคนได้เงิน + 3
    final table คือเหลือเท่าคนที่โต๊ะนี้ พูด icm เฉย ๆ ไม่บอกรางวัลหรือช่วงของทัวร์ คือ bubble
    """
    named = (request.left_pct is not None or request.players_left or request.stage_word
             or request.paid_places or request.bubble_away)
    money = request.buy_in or request.prize_pool
    if not named and not ((request.icm or money) and request.payouts is None):
        return None
    given = tuple(request.payouts or ())
    found = _stage(request, request.entrants or _entrants_from_pool(request) or _default_entrants(request), given)
    said = request.entrants or _entrants_from_pool(request) or request.paid_places
    if not said and found.left < (request.players or 0) and found.entrants < structures.MTT_ENTRANTS:
        # คนนั่งโต๊ะนี้มากกว่าคนที่เหลือในเกม live เล็ก จึงต้องเป็นทัวร์ใหญ่ เช่น 8 คนที่ bubble
        found = _stage(request, structures.MTT_ENTRANTS, given)
    return found


def _default_entrants(request: preflop.Request) -> int:
    if request.paid_places:
        return max(round(request.paid_places / structures.PAID_SHARE), request.players_left or 0,
                   request.paid_places + (request.bubble_away or 0))
    return (structures.DEFAULT_ENTRANTS if (request.players_left or 0) <= structures.DEFAULT_ENTRANTS
            else structures.MTT_ENTRANTS)


def _stage(request: preflop.Request, entrants: int, given: tuple[float, ...]) -> structures.Stage:
    share = (request.paid_places / entrants if request.paid_places and not given
             else None if request.paid_pct is None else request.paid_pct / 100)
    if request.players_left or request.left_pct is not None:
        left = request.players_left or max(1, round(entrants * request.left_pct / 100))
    elif request.bubble_away:
        paid = structures.Stage.bubble(entrants, share, given).paid
        left = min(entrants, paid + request.bubble_away)
    elif request.stage_word == "final":
        left = request.players or TABLE_SIZE
    else:
        return structures.Stage.bubble(entrants, share, given)
    return structures.Stage(entrants, left, share, given)


def _buy_in(request: preflop.Request) -> float:
    return request.buy_in or structures.BUY_IN_THB


def _entrants_from_pool(request: preflop.Request) -> int | None:
    """คนลงจากเงินรางวัลรวม ÷ ค่าซื้อเข้า เช่น pool 15000 ซื้อเข้า 500 คือ 30 คน"""
    if not request.prize_pool:
        return None
    return max(2, round(request.prize_pool / _buy_in(request)))


def pool_thb(request: preflop.Request, found: structures.Stage) -> float:
    """เงินรางวัลรวมเป็นบาท บอกมาก็ใช้ตามนั้น ไม่บอกคือคนลง × ค่าซื้อเข้า"""
    return request.prize_pool or found.entrants * _buy_in(request)


def _others(request: preflop.Request) -> float:
    """สแตกของทุกคนที่โต๊ะอื่นเป็น bb ตามที่พูด ไม่บอกคือเท่าโต๊ะนี้"""
    return request.field_avg or _stack(request)


def payouts(request: preflop.Request) -> icm.Payouts | None:
    """รางวัลที่ใช้แก้ None คือ chip EV ตั้งไม่ได้ raise icm.PayoutError"""
    if request.payouts == ():
        return None
    found = stage(request)
    if found:
        posted = _ante(request) if _mode(request) == "each" else 0.0
        return found.payouts(_players(request), round(_others(request) + posted, 9))
    return icm.Payouts(request.payouts) if request.payouts else None


def payout_problem(request: preflop.Request) -> str | None:
    """ทำไมคิด ICM ไม่ได้ เช่น heads-up จ่ายสามอันดับ หรือเหลือน้อยกว่าคนที่โต๊ะ None ถ้าได้"""
    try:
        chosen = payouts(request)
        if chosen is not None:
            chosen.check(_players(request))
    except icm.PayoutError as error:
        return str(error)
    return None


def _model(request: preflop.Request) -> str:
    chosen = payouts(request)
    if chosen is None:
        return "chip EV"
    found = stage(request)
    if found is None:
        return "ICM " + "/".join(f"{p:g}" for p in chosen.prizes)
    named = request.players_left is None and request.left_pct is None and (request.stage_word or "bubble")
    where = {"bubble": "bubble: ", "final": "final table: "}.get(named, "")
    money = " (in the money)" if found.in_money else ""
    curve = {"given": "real payouts", "live": "live payouts", "mtt": "standard MTT payouts"}[found.curve]
    if found.curve != "given":
        curve += " " + _baht(request, found)
    others = f", others at {_others(request):g}bb each" if chosen.crowd else ""
    # รางวัลจริงไม่ขึ้นกับคนลง ถ้าไม่ได้บอกคนลงก็ไม่ต้องโชว์ 1000 ที่สมมติไว้
    size = (f" of {found.entrants} left ({100 * found.left / found.entrants:.3g}%)"
            if request.entrants or not found.given else " left")
    return f"ICM, {where}{found.left}{size}, {found.paid} paid{money}, {curve}{others}"


def _baht(request: preflop.Request, found: structures.Stage) -> str:
    """รางวัลเป็นบาท เช่น (pool 10,000 THB: 3,880/2,590/1,660/1,110/760 THB) รางวัลเยอะเกินแสดงแค่ pool"""
    pool = pool_thb(request, found)
    prizes = found.prizes()
    if len(prizes) > MAX_PRIZES_SHOWN:
        return f"(pool {pool:,.0f} THB)"
    shown = "/".join(f"{p * pool / found.entrants:,.0f}" for p in prizes)
    return f"(pool {pool:,.0f} THB: {shown} THB)"


@functools.lru_cache(maxsize=64)
def _solve(stack: float, players: int, ante: float, mode: str,
           prizes: icm.Payouts | None = None, fee: float = 0.0) -> coach.Result:
    # ผลเดียวมีทุกที่นั่งทุกสถานการณ์ในโต๊ะ ถามที่นั่งอื่นในสแตกเดิมจึงไม่ต้องแก้ใหม่
    return coach.solve(_spot(stack, players, ante, mode, fee), library=_LIBRARY, payouts=prizes)


def solve_table(request: preflop.Request) -> coach.Result:
    """ผลแก้ของทั้งโต๊ะ ทุกที่นั่งทุกสถานการณ์ ใช้แก้ล่วงหน้าและส่งออกชาร์ตทั้งชุด"""
    return _solve(_stack(request), _players(request), _ante(request), _mode(request),
                  payouts(request), _fee(request))


def missing_seat(request: preflop.Request) -> tuple[str, tuple[str, ...]] | None:
    """(ตำแหน่งที่ไม่มีในโต๊ะขนาดนี้, ตำแหน่งที่มี) เช่นถาม UTG ที่โต๊ะ 4 คน คืน None ถ้าครบ"""
    try:
        names = table(request).names
    except SpotError:
        return None
    asked = (request.hero, request.villain, *request.shovers)
    for seat in asked:
        if seat and _seat(names, seat) not in names:
            return seat, tuple(_label(names, name) for name in names)
    return None



@dataclasses.dataclass(frozen=True)
class SeatProblem:
    """ตำแหน่งที่ไม่มีในโต๊ะ พร้อมเหตุผลที่โต๊ะมีคนเท่านี้ ให้บอกผู้ถามว่าต้องแก้คำถามยังไง"""

    seat: str
    seats: tuple[str, ...]
    source: str                      # said | bubble | left | aof | default คือที่มาของขนาดโต๊ะ
    stage: structures.Stage | None   # ช่วงของทัวร์ถ้าโต๊ะสั้นเพราะทัวร์เหลือคนน้อย
    fits: int | None                 # โต๊ะเล็กสุดที่มีตำแหน่งนี้ None ถ้าไม่มีเลย


def seat_problem(request: preflop.Request) -> SeatProblem | None:
    """เหมือน missing_seat แต่บอกด้วยว่าโต๊ะมีคนเท่านี้เพราะอะไร และโต๊ะกี่คนถึงจะมีตำแหน่งนั้น"""
    missing = missing_seat(request)
    if missing is None:
        return None
    seat, seats = missing
    found = None if request.players or request.aof else stage(request)
    if request.players:
        source = "said"
    elif request.aof:
        source = "aof"
    elif found and found.left < TABLE_SIZE:
        source = "left" if request.players_left or request.left_pct is not None else "bubble"
    else:
        source, found = "default", None
    names = {n: _spot(_stack(request), n, 0.0, "each").names
             for n in range(len(seats) + 1, MAX_PLAYERS + 1)}
    fits = next((n for n, there in names.items() if _seat(there, seat) in there), None)
    return SeatProblem(seat, seats, source, found, fits)

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
    if _ante(request) == 0:
        return "no ante"
    if _mode(request) == "bb":
        return f"BB ante {_ante(request):g}bb"
    return f"ante {_ante(request):g}bb each"


def solved(request: preflop.Request) -> Solved | None:
    """ชาร์ตที่แก้แล้วของผู้ถาม คืน None ถ้าแก้ไม่ได้ เช่นสแตกไม่พอจ่าย blind กับ ante"""
    if payout_problem(request):
        return None
    try:
        result = solve_table(request)
    except SpotError:
        return None
    names = result.spot.names
    hero, villain = _seat(names, request.hero), _seat(names, request.villain)
    if hero not in names or names.index(hero) in result.spot.forced:
        return None
    past = history(names, hero, villain, tuple(_seat(names, s) for s in request.shovers))
    return chart_for(request, result, hero, past)


def chart_for(request: preflop.Request, result: coach.Result, hero: str,
              past: tuple[int, ...]) -> Solved:
    """ชาร์ตของที่นั่ง hero หลัง action past จากผลแก้ทั้งโต๊ะ"""
    names = result.spot.names
    stack = _stack(request)
    seat = names.index(hero)
    node = result.node(seat, past)
    facing = floor.JAM in past
    villain = "+".join(_label(names, names[i]) for i, act in enumerate(past) if act == floor.JAM) or None
    order = list(hands.CLASSES)  # เรียง A..2 แถวต่อแถว ตรงกับ hand_order ในไฟล์ชาร์ต
    action = "call" if facing else "raise"
    actions, mixed = _cells(result.strategy[node.index][:, floor.JAM], action, order)
    model = _model(request)
    if request.aof:
        title = AOF_TITLE.format(model=model)
    else:
        title = TITLE.format(model="ICM MTT" if stage(request) and payouts(request) else model)
    book = {"game": "cash" if request.aof else "tournament", "title": title, "hand_order": order}
    chart = {"stack": stack, "section": "SOLVER", "page": None,
             "hero": _label(names, hero), "villain": villain,
             "scenario": FACING if facing else FIRST_IN, "actions": actions, "mixed": mixed,
             "names": {"raise": "shove"}}
    table = "heads-up" if len(names) == 2 else f"{len(names)}-handed"
    fee = (f", {_fee(request):g}bb fee per player at showdown (rake + jackpot + All-In Fortune)"
           if _fee(request) else "")
    after = " after the ante" if _ante(request) else ""
    note = (f"push/fold Nash, {model}, {table}, all stacks {stack}bb{after}, "
            f"{_ante_words(request)}{fee}, {result.range_pct(seat, past) * 100:.1f}% of hands "
            f"{'call' if facing else 'shove'}, exploitability {result.exploitability:.3f}bb, "
            f"solved in {result.seconds:.1f}s")
    if stack > MAX_STACK:
        # สแตกลึกกว่านี้ Nash จริงมี min-raise กับ limp ด้วย ชาร์ตนี้จึงเป็นแค่ค่าประมาณ
        note += f"; above {MAX_STACK}bb real play also min-raises, treat as approximate"
    return Solved(book, chart, note)
