"""GGPoker tournament hand histories (Omaha, PLO4 or PLO5) read into solver spots.

Each hand gives the seats in preflop order (UTG ... BTN, SB, BB, the order the solver uses), every
stack in big blinds before posting, the ante, the hero's cards, the board, and every action by street.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from pathlib import Path

from plo_equity.cards import parse_cards

_HEADER = re.compile(r"^Poker Hand #(\S+): Tournament #(\d+), (.+?) - Level(\d+)\(([\d,]+)/([\d,]+)\(([\d,]+)\)\) - "
                     r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})")
_BUTTON = re.compile(r"^Table '[^']*' (\d+)-max Seat #(\d+) is the button")
_SEAT = re.compile(r"^Seat (\d+): (.+?) \(([\d,]+) in chips\)")
_ACTION = re.compile(r"^(.+?): (folds|checks|calls|bets|raises)(?: ([\d,]+))?(?: to ([\d,]+))?( and is all-in)?$")
_DEALT = re.compile(r"^Dealt to Hero \[([^\]]+)\]")
_STREET = re.compile(r"^\*\*\* (FLOP|TURN|RIVER) \*\*\* (.*)$")
_SHOWS = re.compile(r"^(.+?): shows \[([^\]]+)\]")
_COLLECTED = re.compile(r"^(.+?) collected ([\d,]+) from pot")
STREETS = ("preflop", "flop", "turn", "river")


def _n(text: str) -> int:
    return int(text.replace(",", ""))


@dataclasses.dataclass(frozen=True)
class Action:
    street: int          # 0 preflop .. 3 river
    player: str
    kind: str            # fold, check, call, bet, raise
    amount: int          # chips added (call/bet) or the total raised to (raise)
    all_in: bool


@dataclasses.dataclass(frozen=True)
class Hand:
    hand_id: str
    time: dt.datetime
    level: int
    sb: int
    bb: int
    ante: int
    players: tuple[str, ...]        # preflop order: UTG ... BTN, SB, BB
    chips: tuple[int, ...]          # stacks before posting, same order
    hero_cards: tuple[int, ...]
    board: tuple[int, ...]          # 0-5 cards
    actions: tuple[Action, ...]
    shown: dict                      # player -> cards shown at showdown
    won: dict                        # player -> chips collected
    hero_blind: int = 0              # small or big blind the hero posted
    table: str = ""

    @property
    def hero(self) -> int:
        return self.players.index("Hero")

    @property
    def stacks_bb(self) -> tuple[float, ...]:
        return tuple(c / self.bb for c in self.chips)

    @property
    def ante_bb(self) -> float:
        return self.ante / self.bb

    def hero_net(self) -> int:
        """Chips the hero won or lost in the hand (uncalled bets are not logged by GG, so a bet that
        everyone folds to counts as won pot minus the full bet)."""
        put = self.ante
        street_put = {0: self.hero_blind}
        for a in self.actions:
            if a.player != "Hero":
                continue
            current = street_put.get(a.street, 0)
            if a.kind in ("call", "bet"):
                street_put[a.street] = current + a.amount
            elif a.kind == "raise":
                street_put[a.street] = a.amount
        put += sum(street_put.values())
        return self.won.get("Hero", 0) - put


def _preflop_order(seats: list[tuple[int, str, int]], button: int, sb_player: str | None, bb_player: str) -> list[tuple[int, str, int]]:
    names = [name for _, name, _ in seats]
    bb_at = names.index(bb_player)
    order = seats[bb_at + 1:] + seats[:bb_at + 1]  # clockwise from the seat after the big blind, BB last
    return order


def parse_hand(text: str) -> Hand:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    head = _HEADER.match(lines[0])
    if not head:
        raise ValueError(f"not a tournament hand: {lines[0][:60]}")
    hand_id, _, _, level, sb, bb, ante, when = head.groups()
    button = int(_BUTTON.match(lines[1]).group(2))
    table = re.match(r"^Table '([^']*)'", lines[1]).group(1)
    seats, actions, board, shown, won = [], [], [], {}, {}
    sb_player = bb_player = None
    hero_blind = 0
    hero_cards: tuple[int, ...] = ()
    street = 0
    for line in lines[2:]:
        if line.startswith("*** SUMMARY"):
            break
        if m := _SEAT.match(line):
            seats.append((int(m.group(1)), m.group(2), _n(m.group(3))))
        elif ": posts small blind" in line:
            sb_player = line.split(":")[0]
            if sb_player == "Hero":
                hero_blind = _n(line.rsplit(" ", 1)[1])
        elif ": posts big blind" in line:
            bb_player = line.split(":")[0]
            if bb_player == "Hero":
                hero_blind = _n(line.rsplit(" ", 1)[1])
        elif m := _DEALT.match(line):
            hero_cards = parse_cards(m.group(1).replace(" ", ""))
        elif m := _STREET.match(line):
            street = STREETS.index(m.group(1).lower())
            cards = re.findall(r"\[([^\]]+)\]", m.group(2))
            board = list(parse_cards(cards[0].replace(" ", ""))) + (
                list(parse_cards(cards[1].replace(" ", ""))) if len(cards) > 1 else [])
        elif m := _ACTION.match(line):
            player, kind, amount, to, all_in = m.groups()
            kind = {"folds": "fold", "checks": "check", "calls": "call", "bets": "bet", "raises": "raise"}[kind]
            value = _n(to) if kind == "raise" else _n(amount) if amount else 0
            actions.append(Action(street, player, kind, value, bool(all_in)))
        elif m := _SHOWS.match(line):
            shown[m.group(1)] = parse_cards(m.group(2).replace(" ", ""))
        elif m := _COLLECTED.match(line):
            won[m.group(1)] = won.get(m.group(1), 0) + _n(m.group(2))
    if bb_player is None:
        raise ValueError(f"{hand_id}: no big blind")
    order = _preflop_order(seats, button, sb_player, bb_player)
    return Hand(hand_id=hand_id, time=dt.datetime.strptime(when, "%Y/%m/%d %H:%M:%S"), level=int(level),
                sb=_n(sb), bb=_n(bb), ante=_n(ante), players=tuple(n for _, n, _ in order),
                chips=tuple(c for _, _, c in order), hero_cards=hero_cards, board=tuple(board),
                actions=tuple(actions), shown=shown, won=won, hero_blind=hero_blind, table=table)


def parse_file(path: Path) -> list[Hand]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = [b for b in re.split(r"\n\s*\n\s*\n", text) if b.strip().startswith("Poker Hand")]
    return sorted((parse_hand(b) for b in blocks), key=lambda h: h.time)


def session_nets(hands: list[Hand]) -> list[int]:
    """Hero's chips won or lost per hand: the change to the next hand's stack (exact, uncalled bets
    included), and the logged actions for the last hand and for every bust (re-entries restart the stack)."""
    nets = []
    for i, hand in enumerate(hands):
        logged = hand.hero_net()
        if i + 1 < len(hands) and logged != -hand.chips[hand.hero]:
            nets.append(hands[i + 1].chips[hands[i + 1].hero] - hand.chips[hand.hero])
        else:  # the last hand, or a bust before a re-entry (the next hand starts a new stack)
            nets.append(logged)
    return nets
