"""GGPoker PLO tournament hand histories -> preflop spots in the solver's seat order.

Each hand gives the table in preflop order (UTG ... BTN, SB, BB) with stacks in big blinds,
the hero's seat name and cards, and every preflop action. GG histories do not say how many
players are left, so ``players_left_curve`` estimates it from the table averages over time:
average stack = chips in play / players left, fitted log-linear in time and pinned to a known
count at one hand (for example the hero's finishing place at the last hand).
"""

from __future__ import annotations

import dataclasses
import datetime
import math
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np

SEAT_NAMES = {
    2: ("SB", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("CO", "BTN", "SB", "BB"),
    5: ("HJ", "CO", "BTN", "SB", "BB"),
    6: ("UTG", "HJ", "CO", "BTN", "SB", "BB"),
    7: ("UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"),
}
HEADER = re.compile(r"Poker Hand #(\S+): Tournament #(\d+), (.*?) - Level(\d+)\(([\d,]+)/([\d,]+)\(([\d,]+)\)\) - "
                    r"(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d)")
SEAT = re.compile(r"^Seat (\d+): (\S+) \(([\d,]+) in chips\)", re.M)
BUTTON = re.compile(r"Seat #(\d+) is the button")
ACTION = re.compile(r"^(\S+): (folds|checks|calls|raises|bets)(?: [\d,]+)?(?: to ([\d,]+))?", re.M)


class HistoryError(ValueError):
    """A hand that cannot be read."""


@dataclasses.dataclass(frozen=True)
class Hand:
    hand_id: str
    tournament: str
    level: int
    bb: int
    ante: int
    played: str                         # "YYYY/MM/DD HH:MM:SS"
    players: tuple[str, ...]            # preflop order UTG ... BTN, SB, BB
    chips: tuple[int, ...]
    hero_cards: str
    actions: tuple[tuple[str, str], ...]  # preflop (player, action)

    @property
    def seat_names(self) -> tuple[str, ...]:
        return SEAT_NAMES[len(self.players)]

    @property
    def stacks_bb(self) -> tuple[float, ...]:
        return tuple(round(c / self.bb, 2) for c in self.chips)

    @property
    def hero_seat(self) -> str:
        return self.seat_names[self.players.index("Hero")]

    @property
    def hero_actions(self) -> tuple[str, ...]:
        return tuple(a for p, a in self.actions if p == "Hero")

    @property
    def facing(self) -> str:
        """What the hero faced at the first decision: first-in, limp or raise."""
        before = []
        for player, action in self.actions:
            if player == "Hero":
                break
            before.append(action)
        return "raise" if "raises" in before else "limp" if "calls" in before else "first-in"

    @property
    def minutes(self) -> float:
        return datetime.datetime.strptime(self.played, "%Y/%m/%d %H:%M:%S").timestamp() / 60


def _preflop_order(seats: list[tuple[int, str, int]], button: int) -> list[tuple[int, str, int]]:
    seats = sorted(seats)
    numbers = [s for s, _, _ in seats]
    # A dead button sits on an empty seat: the last occupied seat before it acts as button.
    at = max((i for i, s in enumerate(numbers) if s <= button), default=len(seats) - 1)
    n = len(seats)
    clockwise = [seats[(at + 1 + k) % n] for k in range(n)]   # SB, BB, first to act ..., button
    if n == 2:
        return [seats[at], seats[(at + 1) % n]]                 # button posts the small blind
    return clockwise[2:] + clockwise[:2]


def parse_hand(text: str) -> Hand:
    head = HEADER.search(text)
    button = BUTTON.search(text)
    hero = re.search(r"Dealt to Hero \[([^\]]+)\]", text)
    if not (head and button and hero) or "*** HOLE CARDS ***" not in text:
        raise HistoryError("not a GG tournament hand with hero cards")
    seats = [(int(a), name, int(c.replace(",", ""))) for a, name, c in SEAT.findall(text)]
    if not 2 <= len(seats) <= 7:
        raise HistoryError(f"{len(seats)} seats")
    order = _preflop_order(seats, int(button[1]))
    names = [n for _, n, _ in order]
    small = re.search(r"^(\S+): posts small blind", text, re.M)
    big = re.search(r"^(\S+): posts big blind", text, re.M)
    if not small or (big and big[1] != names[-1]) or small[1] != names[-2]:
        raise HistoryError("blinds do not follow the button (dead small blind?)")
    preflop = text.split("*** HOLE CARDS ***", 1)[1].split("***", 1)[0]
    return Hand(
        hand_id=head[1], tournament=head[2], level=int(head[4]), bb=int(head[6].replace(",", "")),
        ante=int(head[7].replace(",", "")), played=head[8], players=tuple(n for _, n, _ in order),
        chips=tuple(c for _, _, c in order), hero_cards=hero[1].replace(" ", ""),
        actions=tuple((p, a) for p, a, _ in ACTION.findall(preflop)),
    )


def read_hands(path: Path) -> list[Hand]:
    """Every readable hand in a GG history file, oldest first."""
    blocks = re.split(r"\n\s*\n(?=Poker Hand #)", path.read_text(encoding="utf-8-sig").strip())
    hands = []
    for block in blocks:
        try:
            hands.append(parse_hand(block))
        except HistoryError:
            continue
    return sorted(hands, key=lambda h: h.minutes)


def players_left_curve(hands: list[Hand], total_chips: float, *, pin: tuple[str, int],
                       from_level: int = 1) -> Callable[[Hand], int]:
    """Estimate players left at each hand: total chips / table average, fitted over time.

    ``pin`` = (hand id, players left then) anchors the curve; the slope comes from the fit.
    """
    used = [h for h in hands if h.level >= from_level]
    if len(used) < 2:
        raise HistoryError("need at least two hands to fit players left")
    t = np.asarray([h.minutes for h in used])
    y = np.asarray([math.log(total_chips * len(h.chips) / sum(h.chips)) for h in used])
    slope, intercept = np.polyfit(t, y, 1)
    anchor = next((h for h in hands if h.hand_id == pin[0]), None)
    if anchor is None:
        raise HistoryError(f"pin hand {pin[0]} not found")
    shift = math.log(pin[1]) - (intercept + slope * anchor.minutes)

    def left(hand: Hand) -> int:
        return max(len(hand.chips), round(math.exp(intercept + slope * hand.minutes + shift)))
    return left
