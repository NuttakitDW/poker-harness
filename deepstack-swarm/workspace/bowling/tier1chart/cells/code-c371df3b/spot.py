"""A Spot: who sits where, with how many big blinds, and what they posted.

Stacks are in big blinds, counted before anything is posted, in preflop action order.
The last two seats are always SB and BB (heads-up: SB then BB).

A stack too short to cover its ante and blind posts what it has, ante first (the same
order pokerkit uses), and is all-in by posting: it never acts and always sees the showdown.

A fee is charged to every player in a showdown, outside the pot (GGPoker All-in or Fold
takes rake, jackpot and All-In Fortune fees this way; the hand history never shows them).
"""

from __future__ import annotations

import dataclasses
import math

MIN_PLAYERS, MAX_PLAYERS = 2, 9
ANTE_MODES = ("each", "bb")
ALL_IN_EPSILON = 1e-9
_TAIL = ("LJ", "HJ", "CO", "BTN", "SB", "BB")


class SpotError(ValueError):
    """A spot that cannot be dealt. The message says what to fix."""


def position_names(n: int) -> tuple[str, ...]:
    if n <= len(_TAIL):
        names = _TAIL[-n:]
        return ("UTG",) + names[1:] if n == 6 else names
    early = ("UTG",) + tuple(f"UTG+{i}" for i in range(1, n - len(_TAIL)))
    return early + _TAIL


@dataclasses.dataclass(frozen=True)
class Spot:
    stacks: tuple[float, ...]
    sb: float = 0.5
    bb: float = 1.0
    ante: float = 0.0         # "each": every seat posts this. "bb": the BB posts this for the table.
    ante_mode: str = "each"
    fee: float = 0.0          # bb each player pays when the hand reaches a showdown

    def __post_init__(self) -> None:
        object.__setattr__(self, "stacks", tuple(float(s) for s in self.stacks))
        n = len(self.stacks)
        if not MIN_PLAYERS <= n <= MAX_PLAYERS:
            raise SpotError(f"need {MIN_PLAYERS}-{MAX_PLAYERS} players, got {n}")
        if not all(math.isfinite(s) and s > 0 for s in self.stacks):
            raise SpotError(f"stacks must be positive numbers of big blinds, got {self.stacks}")
        if not (0 < self.sb <= self.bb and math.isfinite(self.bb)):
            raise SpotError(f"need 0 < sb <= bb, got sb={self.sb} bb={self.bb}")
        if not (math.isfinite(self.ante) and self.ante >= 0):
            raise SpotError(f"ante must be >= 0, got {self.ante}")
        if not (math.isfinite(self.fee) and self.fee >= 0):
            raise SpotError(f"fee must be >= 0, got {self.fee}")
        if self.ante_mode not in ANTE_MODES:
            raise SpotError(f"ante_mode must be one of {ANTE_MODES}, got {self.ante_mode!r}")

    @property
    def n(self) -> int:
        return len(self.stacks)

    @property
    def names(self) -> tuple[str, ...]:
        return position_names(self.n)

    @property
    def blinds(self) -> tuple[float, ...]:
        """Blind each seat actually posts: whatever is left after its ante, up to the blind."""
        due = (0.0,) * (self.n - 2) + (self.sb, self.bb)
        return tuple(min(blind, stack - ante) for blind, stack, ante in zip(due, self.stacks, self.antes))

    @property
    def antes(self) -> tuple[float, ...]:
        """Ante each seat actually posts, never more than its stack."""
        due = ((0.0,) * (self.n - 1) + (self.ante,) if self.ante_mode == "bb"
               else (self.ante,) * self.n)
        return tuple(min(ante, stack) for ante, stack in zip(due, self.stacks))

    @property
    def forced(self) -> tuple[int, ...]:
        """Seats all-in by posting: nothing left behind, so no decision to make."""
        return tuple(s for s in range(self.n) if self.stacks[s] - self.posts[s] <= ALL_IN_EPSILON)

    @property
    def posts(self) -> tuple[float, ...]:
        return tuple(b + a for b, a in zip(self.blinds, self.antes))
