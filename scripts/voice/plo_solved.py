"""Answer a PLO preflop spot from the solved 20bb and 40bb MTT charts (chip EV).

The charts come from plo_premium_proof: six-handed PLO4, pot-limit raises, full postflop
play, two CFR seeds averaged. 20bb has no ante; the 40bb MTT game has a 0.116bb ante from
every player that plays for the pot but is left out of the preflop pot-limit size.
ICM spots and short stacks stay with plo_advisor.
"""

from __future__ import annotations

import collections
import dataclasses
import itertools
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import plo_advisor  # noqa: E402
import plo_type  # noqa: E402
import preflop  # noqa: E402
import spot  # noqa: E402
from plo_premium_proof.preflop_chart import SEATS, SpotError, chart, six_max_seat, spot_events  # noqa: E402

CHARTS = {20: "20bb", 40: "mtt40"}
CHART_ANTE = {20: 0.0, 40: 0.116}
_BARE_RANKS = re.compile(r"(?<![A-Za-z0-9+.])([2-9TJQKA]{4})(?![A-Za-z0-9])", re.IGNORECASE)
_SHAPE_NAME = {(2, 2): "double-suited", (2, 1, 1): "single-suited", (1, 1, 1, 1): "rainbow",
               (3, 1): "three-flush", (4,): "monotone"}
_SUIT = {"♠": "s", "♥": "h", "♦": "d", "♣": "c", "s": "s", "h": "h", "d": "d", "c": "c"}
_PRETTY = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}


@dataclasses.dataclass(frozen=True)
class Answer:
    status: str
    message: str
    request: preflop.Request


def routes(prompt: str, memory: preflop.Request | None = None) -> bool:
    """A PLO spot at a solved stack depth that is not asking for ICM."""
    if not plo_advisor.routes(prompt, memory):
        return False
    request, _ = plo_advisor._context(prompt, memory)
    return request.stack is not None and request.stack > 10 and not request.icm and not request.payouts


def _candidates(hand: plo_type.Hand) -> list[tuple[str, ...]]:
    """Every physical hand matching the description (exact cards give just one)."""
    if hand.cards:
        cards = []
        text = hand.cards
        index = 0
        while index < len(text):
            rank = text[index]
            cards.append(rank.replace("1", "T") + _SUIT[text[index + 1].lower()])
            index += 2
        return [tuple(cards)]
    found = []
    for suits in itertools.product("shdc", repeat=4):
        cards = tuple(r + s for r, s in zip(hand.ranks, suits))
        if len(set(cards)) != 4:
            continue
        counts = sorted(collections.Counter(suits).values(), reverse=True)
        if hand.suiting is not None:
            if hand.suiting.double and counts != [2, 2]:
                continue
            if not hand.suiting.suited and counts != [1, 1, 1, 1]:
                continue
            if hand.suiting.suited and not hand.suiting.double:
                group = hand.suiting.suited_ranks
                if group:  # exactly these ranks share one suit, and no other card has it
                    shared = {s for r, s in zip(hand.ranks, suits) if r in group}
                    same = [r for r, s in zip(hand.ranks, suits) if s in shared]
                    if len(shared) != 1 or sorted(same) != sorted(group) or counts.count(2) > 1:
                        continue
                elif counts != [2, 1, 1]:
                    continue
        found.append(cards)
    return found


def _pretty(cards: tuple[str, ...]) -> str:
    order = "23456789TJQKA"
    ranked = sorted(cards, key=lambda c: order.index(c[0]), reverse=True)
    return "".join(c[0] + _PRETTY[c[1]] for c in ranked)


def _label(option, lang: str, to_call: float) -> str:
    th = lang != "EN"
    if option.action == "fold":
        return "fold"
    if option.action == "check":
        return "check"
    if option.action == "call":
        verb = "limp" if to_call <= 1.0 + 1e-9 and option.total <= 1.0 + 1e-9 else "call"
        amount = f"{option.total:g}bb"
    else:
        verb = "raise" + (" ถึง" if th else " to")
        amount = f"{option.total:g}bb"
    return f"{verb} {amount}" + (" (all-in)" if option.all_in else "")


def _summary(decision, lang: str) -> str:
    ordered = sorted(decision.options, key=lambda o: -o.frequency)
    top, second = ordered[0], ordered[1]
    th = lang != "EN"
    name = lambda o: _label(o, lang, decision.to_call).split(" ")[0]  # noqa: E731
    if top.frequency >= 0.8:
        return (f"→ {name(top)} เกือบทุกครั้ง" if th else f"→ Almost always {name(top)}.")
    if top.frequency >= 0.6:
        return (f"→ ส่วนใหญ่ {name(top)}" if th else f"→ Mostly {name(top)}.")
    return (f"→ ผสม {name(top)} กับ {name(second)}" if th else f"→ Mixed: {name(top)} or {name(second)}.")


# A follow-up that names one seat plus an action by that seat ("what if BTN 3bets me?",
# "ถ้า CO เปิดมาล่ะ") is about an opponent: keep the remembered hero and make that seat the villain.
_SEAT_WORD = r"(?:UTG\+1|UTG|LJ|HJ|MP|EP|CO|BTN|SB|BB|button|cutoff|hijack|lojack|small blind|big blind)"
_VILLAIN_ACTS = re.compile(
    rf"(?i){_SEAT_WORD}\s*(?:player\s*)?(?:opens?|opened|raises?|raised|3-?bets?|4-?bets?|5-?bets?|limps?|limped"
    rf"|shoves?|jams?|เปิด|รีเรส|รี|ลิมป์|limp|3-?bet|4-?bet|5-?bet)|(?:\bme\b|ใส่ผม|ใส่เรา|มาที่ผม|มาหาผม)")
_HERO_MOVES = re.compile(rf"(?i)(?:from|on|at|in)\s+(?:the\s+)?{_SEAT_WORD}|(?:อยู่|ที่|ตำแหน่ง)\s*{_SEAT_WORD}")


def _follow_up(prompt: str, request: preflop.Request, memory: preflop.Request | None) -> preflop.Request:
    """Read a PLO follow-up against the remembered spot instead of as a fresh question."""
    if memory is None or memory.game != "plo" or memory.hero is None:
        return request
    said = spot.read(prompt)
    if said.hero is None or said.villain is not None:
        return request  # no seat, or both seats already given ("BTN vs CO open")
    if _VILLAIN_ACTS.search(prompt) and said.hero != memory.hero and not _HERO_MOVES.search(prompt):
        return dataclasses.replace(request, hero=memory.hero, villain=said.hero,
                                   scenario=said.scenario or "RFI")
    if said.scenario is None:  # only the hero's seat changed: start again from first in
        return dataclasses.replace(request, hero=said.hero, villain=None, scenario=None)
    return request


def _by_suit_pattern(book, hand, options, hero, villain, request, events, spot_name, th, first_seat) -> Answer:
    """Ranks without an exact suit layout: the solver's mix averaged within each suit pattern."""
    groups: dict[str, list] = collections.defaultdict(list)
    order_ranks = "AKQJT98765432"
    for cards in options:
        counts = collections.Counter(c[1] for c in cards)
        shape = _SHAPE_NAME[tuple(sorted(counts.values(), reverse=True))]
        # name each layout by the ranks that share a suit, e.g. "single-suited A8" or "double-suited A8+76"
        suited = sorted(("".join(sorted((c[0] for c in cards if c[1] == suit), key=order_ranks.index))
                         for suit, n in counts.items() if n >= 2), key=lambda g: order_ranks.index(g[0]))
        groups[f"{shape} {'+'.join(suited)}".strip()].append(cards)
    try:
        sample = book.decide(options[0], hero, events, spot_name)
    except SpotError as exc:
        return Answer("unsupported_spot", str(exc), request)
    order = sorted(groups, key=lambda name: (["double-suited", "single-suited", "three-flush", "rainbow",
                                               "monotone"].index(name.split(" ")[0]), name))
    lines = [(f"{hand.ranks}: คำตอบขึ้นกับว่าไพ่ใบไหนดอกเดียวกัน ({hero}, {spot_name})" if th else
              f"{hand.ranks}: the answer depends on which cards share a suit ({hero}, {spot_name}).").replace(
                  "UTG", first_seat)]
    for shape in order:
        if shape not in groups:
            continue
        mixes = {}
        for cards in groups[shape]:
            decision = book.decide(cards, hero, events, spot_name)
            for option in decision.options:
                mixes[option.action] = mixes.get(option.action, 0.0) + option.frequency / len(groups[shape])
        shown = sorted(sample.options, key=lambda o: -mixes[o.action])
        text = " · ".join(f"{_label(o, 'TH' if th else 'EN', sample.to_call)} {mixes[o.action]:.0%}" for o in shown)
        lines.append(f"  {shape}: {text}")
    example = " ".join(groups[order[0]][0])
    lines.append(f"บอกดอกให้ครบเพื่อคำตอบที่แม่นยำ เช่น {example}" if th
                 else f"Give the exact suits for a precise answer, e.g. {example}.")
    return Answer("by_suit_pattern", "\n".join(lines), request)


def answer(prompt: str, memory: preflop.Request | None = None, lang: str = "EN") -> Answer | None:
    if not routes(prompt, memory):
        return None
    request, _ = plo_advisor._context(prompt, memory)
    request = _follow_up(prompt, request, memory)
    th = lang != "EN"
    asked = plo_advisor._normalized_lookup(prompt)
    if asked is not None and asked.error:
        return Answer("invalid_hand", ("มือ PLO ไม่ถูกต้อง: " if th else "Invalid PLO hand: ") + asked.error, request)
    hand = asked.hand if asked is not None else None
    bare = _BARE_RANKS.search(prompt)
    if hand is None and bare is not None:  # e.g. "9663 UTG": ranks without suits
        hand = plo_type.Hand(plo_type.sorted_ranks(bare.group(1).upper()), None)
    reused = False
    if hand is None and memory is not None and memory.game == "plo" and memory.plo_hand:
        remembered = plo_advisor._normalized_lookup(memory.plo_hand)
        hand = remembered.hand if remembered is not None and not remembered.error else None
        reused = hand is not None
    if hand is None:
        return Answer("missing_hand", "ขอไพ่ PLO สี่ใบ เช่น As Ks Qd 9c หรือ 9876 ds" if th
                      else "Give the four-card hand, e.g. As Ks Qd 9c or 9876 ds.", request)
    assumed_rainbow = hand.suits_assumed or (hand.suiting is None and not hand.cards)
    if assumed_rainbow:  # no suits given: read it as rainbow (four different suits)
        hand = plo_type.from_shape(hand.ranks, "rainbow")
    request = dataclasses.replace(request, plo_hand=plo_advisor._remembered_hand(hand))
    stack = request.stack
    name = CHARTS.get(int(stack)) if float(stack).is_integer() else None
    if name is None:
        return Answer("unsupported_spot", (
            f"ตอนนี้มีชาร์ตที่ solve แล้วสำหรับ 20bb (ไม่มี ante) และ 40bb MTT (ante 0.116bb) ยังไม่มี {stack:g}bb"
            if th else f"Solved charts exist for 20bb (no ante) and 40bb MTT (0.116bb ante); {stack:g}bb is not solved yet."),
            request)
    hero, villain = six_max_seat(request.hero), six_max_seat(request.villain)
    # LJ is the usual 6-max name for UTG: same seat, so answer in the name the player used.
    first_seat = "LJ" if "LJ" in {(request.hero or "").upper(), (request.villain or "").upper()} else "UTG"
    renamed = [f"{said} = {seat}" for said, seat in ((request.hero, hero), (request.villain, villain))
               if said and seat and said.upper() not in (seat, "LJ")]
    if hero is not None and hero == villain:
        return Answer("unsupported_spot", f"{request.hero} กับ {request.villain} คือที่นั่งเดียวกันในโต๊ะ 6 คน" if th
                      else f"{request.hero} and {request.villain} are the same seat at 6-max.", request)
    if request.villain is not None and villain is None:
        return Answer("unsupported_spot", f"{request.villain} ไม่มีในโต๊ะ 6 คน (UTG, HJ, CO, BTN, SB, BB)" if th
                      else f"{request.villain} is not a 6-max seat (UTG, HJ, CO, BTN, SB, BB).", request)
    if hero is None or hero == "BB" and villain is None:
        return Answer("missing_spot", "บอกตำแหน่ง UTG, HJ, CO, BTN, SB หรือ BB (BB ต้องมีคน limp หรือ raise มาก่อน)" if th
                      else "Give a seat: UTG, HJ, CO, BTN, SB, or BB facing a limp or raise.", request)
    if request.players not in (None, 6) or request.unsupported_history or request.shovers:
        return Answer("unsupported_spot", "ชาร์ตนี้ตอบได้เฉพาะโต๊ะ 6 คน และมีคนเข้า pot ก่อนหน้าไม่เกินหนึ่งคน" if th
                      else "These charts cover 6-handed spots with at most one player in before you.", request)
    try:
        events, spot_name = spot_events(hero, villain, request.scenario)
    except SpotError as exc:
        return Answer("unsupported_spot", str(exc), request)
    try:
        book = chart(name)
    except FileNotFoundError:
        return Answer("unsupported_spot", "ชาร์ต PLO ที่ solve แล้วยังไม่ได้ติดตั้งบนเครื่องนี้" if th
                      else "The solved PLO charts are not installed on this server yet.", request)
    options = _candidates(hand)
    if not options:
        return Answer("invalid_hand", "ไม่มีไพ่ที่ตรงกับคำบอกนี้" if th else "No four cards match that description.", request)
    buckets = {book.bucket(cards) for cards in options}
    if len(buckets) > 1:
        return _by_suit_pattern(book, hand, options, hero, villain, request, events, spot_name, th, first_seat)
    cards = options[0]
    try:
        decision = book.decide(cards, hero, events, spot_name)
    except SpotError as exc:
        return Answer("unsupported_spot", str(exc), request)
    ante = CHART_ANTE[int(stack)]
    facing = decision.options and any(o.action == "fold" for o in decision.options) and bool(decision.line) \
        and any("raise" in step for step in decision.line)
    game = (f"PLO 40bb MTT solver (6 คน, ante {ante:g}bb ทุกคน, chip EV)" if th and ante
            else "PLO 20bb solver (6 คน, ไม่มี ante, chip EV)" if th
            else f"PLO 40bb MTT solver (6-max, {ante:g}bb ante each, chip EV)" if ante
            else "PLO 20bb solver (6-max, no ante, chip EV)")
    show = lambda text: re.sub(r"\bUTG\b", first_seat, text)  # noqa: E731
    lines = [game,
             show(f"Spot: {hero}, {spot_name}") + (f" ({', '.join(renamed)} at 6-max)" if renamed else "")
             + (show(f" · line: {', '.join(decision.line[-4:])}") if decision.line else ""),
             (f"ไพ่: {_pretty(cards)}" + (" (ไม่ได้บอกดอก ถือว่า rainbow)" if assumed_rainbow else "")
              + (" (มือเดิม)" if reused else "")
              + f" · pot {decision.pot:.2f}bb" if th else
              f"Hand: {_pretty(cards)}" + (" (no suits given, assumed rainbow)" if assumed_rainbow else "")
              + (" (same hand as before)" if reused else "")
              + f" · pot {decision.pot:.2f}bb")
             + (f", ต้องจ่าย {decision.to_call:g}bb" if th and facing else
                f", {decision.to_call:g}bb to call" if facing else ""),
             " · ".join(f"{_label(o, lang, decision.to_call)} {o.frequency:.0%}"
                        for o in sorted(decision.options, key=lambda o: -o.frequency)),
             _summary(decision, lang)]
    if request.ante is not None and abs(request.ante - ante) > 1e-9:
        lines.append(f"หมายเหตุ: ชาร์ตนี้ใช้ ante {ante:g}bb ไม่ใช่ {request.ante:g}bb" if th
                     else f"Note: this chart uses a {ante:g}bb ante, not {request.ante:g}bb.")
    lines.append("มือที่คล้ายกันใช้กลยุทธ์กลุ่มเดียวกัน (780 กลุ่ม) · ไม่ใช่ ICM" if th
                 else "Similar hands share one strategy group (780 groups) · chip EV, not ICM.")
    return Answer("solved_chart", "\n".join(lines), request)
