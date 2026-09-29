"""Route one exact PLO hand in a tournament spot without inventing solver output."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import plo_type
import preflop
import spot
from plo_icm.config import SUNDAY_PAYOUTS
from plo_icm.abstraction import resolve_hand
from plo_icm.config import Config, ConfigError
from plo_icm.hand_advice import solve_hand

_PLO = re.compile(r"(?i)(?<![a-z])(?:plo|omaha)(?![a-z])|โอมาฮา|พีแอลโอ|เพียโล")
_ICM = re.compile(r"(?i)(?<![a-z])icm|bubble|บับเบิล|ใกล้เข้าเงิน")
_SUNDAY = re.compile(r"(?i)sunday\s+classic\s+mini|plo\s+sunday|ซันเดย์")
_FACING = re.compile(r"(?i)\b(?:vs|facing|open|3-?bet|raise)\b|เจอ|เปิด")
_PRIOR_ACTION = re.compile(r"(?i)\b(?:vs\.?|versus|facing)\b|เจอ|โดน")
_OTHER_VARIANT = re.compile(r"(?i)(?<![a-z])(?:nlh|hold\s*'?em|texas)(?![a-z])")


@dataclasses.dataclass(frozen=True)
class Advice:
    status: str
    message: str
    request: preflop.Request
    hand: plo_type.Hand | None = None


def _context(prompt: str, memory: preflop.Request | None) -> tuple[preflop.Request, bool]:
    inherited = memory if memory is not None and memory.game == "plo" else preflop.Request(game="plo")
    said = spot.read(prompt)
    merged = spot.merge(said, inherited)
    named_sunday = bool(_SUNDAY.search(prompt))
    sunday_before = (bool(inherited.payouts)
                     and tuple(inherited.payouts) == SUNDAY_PAYOUTS[:len(inherited.payouts)])
    custom_payout_now = said.payouts is not None
    confirmed_default = bool(_PLO.search(prompt) and (said.icm or _ICM.search(prompt)))
    default_sunday = confirmed_default and inherited.payouts is None
    sunday = (named_sunday or sunday_before or default_sunday) and not custom_payout_now
    merged_remaining = said.players_left if said.players_left is not None else merged.players_left
    remaining = ((merged_remaining if merged_remaining is not None else 76)
                 if sunday else merged.players_left)
    payouts = SUNDAY_PAYOUTS[:min(remaining, len(SUNDAY_PAYOUTS))] if sunday else merged.payouts
    prior_history = inherited.unsupported_history
    if said.players_left is not None and prior_history == "tournament stage needs an exact remaining count":
        prior_history = None
    pending_history = merged.unsupported_history or prior_history
    if said.stage_word is not None and said.players_left is None:
        pending_history = "tournament stage needs an exact remaining count"
    if _PRIOR_ACTION.search(prompt) and merged.villain is None:
        pending_history = "facing action without a complete opener"
    request = dataclasses.replace(
        merged,
        game="plo",
        stack=said.stack if said.stack is not None else merged.stack,
        icm=bool(_ICM.search(prompt)) or merged.icm,
        entrants=(merged.entrants or 515) if sunday else merged.entrants,
        players_left=remaining,
        ante=(.1 if merged.ante is None else merged.ante) if sunday else merged.ante,
        ante_mode=(merged.ante_mode or "each") if sunday else merged.ante_mode,
        field_avg=(merged.field_avg if merged.field_avg is not None else merged.stack or 10)
        if sunday else merged.field_avg,
        payouts=payouts,
        unsupported_history=pending_history,
    )
    return request, sunday


def _spot_signal(prompt: str) -> bool:
    said = spot.read(prompt)
    return bool(said.hero or said.stack is not None or said.icm or said.ante is not None
                or said.ante_mode or said.villain or said.scenario or said.players_left
                or said.entrants or said.field_avg or said.payouts is not None
                or _ICM.search(prompt) or _SUNDAY.search(prompt))


def explicit_other_variant(prompt: str) -> bool:
    return bool(_OTHER_VARIANT.search(prompt))


def routes(prompt: str, memory: preflop.Request | None = None) -> bool:
    """Whether this turn belongs to the exact-hand PLO spot flow."""
    if explicit_other_variant(prompt):
        return False
    explicit_plo = bool(_PLO.search(prompt))
    remembered_plo = memory is not None and memory.game == "plo"
    if not explicit_plo and not remembered_plo:
        return False
    asked = _normalized_lookup(prompt)
    recognized_hand = asked is not None and (asked.hand is not None or asked.error is not None)
    return ((explicit_plo and _spot_signal(prompt))
            or (remembered_plo and (recognized_hand or _spot_signal(prompt))))


def _remembered_hand(hand: plo_type.Hand) -> str:
    if hand.cards:
        return hand.cards
    if hand.suiting is None:
        return hand.ranks
    if hand.suiting.double:
        return f"{hand.ranks} ds"
    if not hand.suiting.suited:
        return f"{hand.ranks} rainbow"
    suffix = "".join(hand.suiting.suited_ranks)
    return f"{hand.ranks} ss {suffix}" if suffix else f"{hand.ranks} ss"


def _shown_hand(hand: plo_type.Hand) -> str:
    if hand.cards:
        return hand.cards
    ranks = "-".join(hand.ranks)
    suited = hand.suiting.suited_ranks if hand.suiting else ()
    if not suited:
        return ranks
    group = "/".join(suited)
    available = list(suited)
    other_suits = iter("dhc")
    exact_cards = []
    for rank in hand.ranks:
        if rank in available:
            available.remove(rank)
            exact_cards.append(rank + "s")
        else:
            exact_cards.append(rank + next(other_suits))
    exact = " ".join(exact_cards)
    return f"{ranks}; {group} share one suit (for example {exact})"


_SUIT_ASCII = {"♠": "s", "♥": "h", "♦": "d", "♣": "c",
               "s": "s", "h": "h", "d": "d", "c": "c"}
_EXACT_CARD = re.compile(r"(10|[AKQJT2-9])([shdc♠♥♦♣])", re.IGNORECASE)
_SEATS = {"UTG": 0, "HJ": 1, "CO": 2, "BTN": 3, "SB": 4}


def _normalized_lookup(prompt: str) -> plo_type.Asked | None:
    """Accept the compact chat spelling while keeping plo_type's strict parser."""
    text = re.sub(r"(?i)(UTG|HJ|CO|BTN|SB|BB)(?=[AKQJT2-9]{4}(?:ds|ss|rb|rainbow))",
                  r"\1 ", prompt)
    text = re.sub(r"(?i)([AKQJT2-9]{4})(ds|rb|rainbow)(?![a-z])", r"\1 \2", text)
    return plo_type.lookup(text)


def _physical_hand(hand: plo_type.Hand) -> tuple[str, ...]:
    if hand.cards:
        cards = tuple(rank.upper().replace("10", "T") + _SUIT_ASCII[suit.lower()]
                      for rank, suit in _EXACT_CARD.findall(hand.cards))
        return resolve_hand(hand.ranks, exact=cards)
    shape = None
    group: tuple[str, ...] = ()
    if hand.suiting is not None:
        if hand.suiting.double:
            shape = "double-suited"
        elif not hand.suiting.suited:
            shape = "rainbow"
        else:
            shape = "single-suited"
            group = hand.suiting.suited_ranks
    return resolve_hand(hand.ranks, shape=shape, suited_group=group)


def _config(request: preflop.Request) -> Config:
    stack = request.stack
    players = request.players_left if request.players_left is not None else 76
    payouts = request.payouts if request.payouts is not None else SUNDAY_PAYOUTS[:min(players, 75)]
    outside = request.field_avg if request.field_avg is not None else stack
    mode = "individual" if request.ante_mode in (None, "each") else request.ante_mode
    return Config(stacks=(stack,) * 6, payouts=payouts, players_remaining=players,
                  outside_stack=outside, ante=.1 if request.ante is None else request.ante,
                  ante_mode=mode, iterations=1_000_000, seed=17,
                  time_limit=None, max_nodes=500_000, max_infosets=100_000)


def _format_result(result, request: preflop.Request, sunday: bool, lang: str,
                   hand: tuple[str, ...]) -> str:
    action = "RAISE" if result.action == "raise_2bb" else result.action.upper()
    amount = f" to {result.amount:g}bb" if result.action in ("call", "raise_2bb", "pot") else ""
    rows = []
    for name, value in result.values.ev.items():
        uncertainty = result.values.se_vs_best[name]
        se = "SE unavailable" if not isinstance(uncertainty, (int, float)) or not uncertainty < float("inf") \
            else f"SE vs best ${uncertainty:.2f}"
        raise_amount = result.amounts.get(name, 2.0)
        label = f"Raise to {raise_amount:g}bb" if name == "raise_2bb" else name.title()
        rows.append(f"{label} ${value:.2f} ({se})")
    outside_count = max((request.players_left or 76) - 6, 0)
    table_stack = request.stack or 10
    outside = request.field_avg if request.field_avg is not None else table_stack
    mode = "individual" if request.ante_mode in (None, "each") else request.ante_mode
    if lang == "EN":
        profile = (f"Sunday Classic Mini assumptions: {request.players_left or 76} remaining, 75 paid originally, "
                   f"{request.ante if request.ante is not None else .1:g}bb {mode} ante, six equal "
                   f"{table_stack:g}bb table stacks before forced posts, outside field "
                   f"{outside_count} × {outside:g}bb."
                   if sunday else "Custom payout assumptions supplied in this spot.")
        close = [("Raise" if name == "raise_2bb" else name.title())
                 for name, value in result.values.ev.items()
                 if name != result.values.best
                 and isinstance(result.values.se_vs_best[name], (int, float))
                 and result.values.ev[result.values.best] - value <= 2 * result.values.se_vs_best[name]]
        comparison = ("Close comparison at roughly two sampling SE: " + ", ".join(close) + "."
                      if close else "No alternative was within roughly two reported sampling SE of the selected action.")
        return "\n".join([
            f"Provisional model action: {action}{amount}.",
            "Resolved hand: " + " ".join(hand) + ".",
            f"Spot: {request.hero}, {table_stack:g}bb, unopened.",
            "Action EVs: " + "; ".join(rows) + ".",
            f"Sampling: {result.samples} complete paired rollouts, ESS {result.values.ess:.1f}; "
            f"{result.untrained_fraction:.0%} of rollout decisions used the explicit uniform fallback.",
            comparison,
            profile,
            "This is one-step action selection under frozen learned continuation policies with uniform fallback. Unraised preflop "
            "choices are fold/limp/raise-to-2bb; pot raises remain for 3-bets and later streets. Not GTO. "
            "Sampling SE excludes training/model error.",
        ])
    profile = (f"สมมติฐาน Sunday Classic Mini: เหลือ {request.players_left or 76} คน เดิมจ่าย 75 อันดับ, "
               f"ante {request.ante if request.ante is not None else .1:g}bb แบบ {mode}, "
               f"ทุกคนที่โต๊ะ {table_stack:g}bb ก่อนลง blind/ante, นอกโต๊ะ {outside_count} คน × {outside:g}bb"
               if sunday else "ใช้ payout ที่ระบุใน spot นี้")
    return "\n".join([
        f"Action โดยประมาณ: {action}{amount}",
        "ไพ่ที่ resolve: " + " ".join(hand),
        f"Spot: {request.hero}, {table_stack:g}bb, ยังไม่มีคนเปิด",
        "EV ของแต่ละ action: " + "; ".join(rows),
        f"สุ่มครบ {result.samples} ชุด, ESS {result.values.ess:.1f}; "
        f"{result.untrained_fraction:.0%} ของจุดตัดสินใจใช้ uniform fallback เพราะฝึกยังจำกัด",
        profile,
        "เป็นการเลือก action หนึ่งจังหวะภายใต้ frozen abstract continuation policies: ก่อนมีคน raise ใช้ fold/limp/raise 2bb; "
        "pot raise ใช้กับ 3-bet และ street หลัง ๆ; "
        "ไม่ใช่ GTO และ sampling SE ไม่รวม training/model error",
    ])


def advise(prompt: str, memory: preflop.Request | None = None, lang: str = "EN") -> Advice | None:
    """Return advice routing only for a PLO spot, never for ordinary hand classification."""
    if not routes(prompt, memory):
        return None
    asked = _normalized_lookup(prompt)
    request, sunday = _context(prompt, memory)
    if asked is not None and asked.error:
        prefix = "Invalid PLO hand" if lang == "EN" else "มือ PLO ไม่ถูกต้อง"
        return Advice("invalid_hand", f"{prefix}: {asked.error}", request)
    hand = asked.hand if asked is not None else None
    if hand is None and memory is not None and memory.game == "plo" and memory.plo_hand:
        remembered = _normalized_lookup(memory.plo_hand)
        hand = remembered.hand if remembered is not None and not remembered.error else None
    if hand is None:
        message = ("Please give the exact four-card hand, including the full suit group, "
                   "for example AK74 ss AK7 or As Ks 7s 4d. I saved the PLO spot."
                   if lang == "EN" else
                   "ขอไพ่ PLO ให้ครบสี่ใบและบอกกลุ่มดอกให้ครบ เช่น AK74 ss AK7 หรือ As Ks 7s 4d "
                   "ผมจำ spot PLO นี้ไว้แล้ว")
        return Advice("missing_hand", message, request)

    request = dataclasses.replace(request, plo_hand=_remembered_hand(hand))
    unopened = (request.villain is None and request.scenario in (None, "RFI")
                and not request.unsupported_history)
    if request.hero not in _SEATS or request.stack is None:
        return Advice("missing_spot", "Give an unopened UTG, HJ, CO, BTN, or SB position and a stack up to 10bb.", request, hand)
    if not 0 < request.stack <= 10:
        return Advice("unsupported_spot", "This first version supports effective stacks above 0 and up to 10bb.", request, hand)
    if request.players not in (None, 6):
        return Advice("unsupported_spot", "This PLO ICM engine currently supports six-handed tables only.", request, hand)
    if request.seat_stacks:
        return Advice("unsupported_spot", "Per-seat stack overrides are not supported by this hand-advice route yet.", request, hand)
    said_now = spot.read(prompt)
    if request.left_pct is not None or (said_now.stage_word is not None
                                        and said_now.players_left is None):
        return Advice("unsupported_spot", "Give the exact number of players remaining for this tournament stage.", request, hand)
    if not unopened:
        return Advice("unsupported_spot", "This first version supports unopened pots only; this prior-action history is not solved.", request, hand)
    if not request.icm and request.payouts in (None, ()):
        return Advice("missing_payouts", "Say ICM or provide an ordered payout list before requesting a dollar-EV action.", request, hand)
    try:
        physical = _physical_hand(hand)
        config = _config(request)
    except (ValueError, ConfigError) as exc:
        return Advice("ambiguous_hand", f"Cannot resolve this solver input: {exc}", request, hand)
    try:
        result = solve_hand(config, seat=_SEATS[request.hero], hand=physical)
    except (ValueError, RuntimeError) as exc:
        message = f"The bounded approximation could not produce a supported action: {exc}"
        return Advice("insufficient_sampling", message, request, hand)
    return Advice("approximate_action", _format_result(result, request, sunday, lang, physical), request, hand)
