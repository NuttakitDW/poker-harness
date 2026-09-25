"""ICM: what a stack is worth in prize money (Malmuth-Harville).

A player finishes first with chance stack / chips in play. Given who is already placed,
the next place goes the same way among the rest. A player's value is the sum over places of
chance x prize. Players who bust in the same hand place by their stack at the start of the
hand, bigger first; equal stacks split those places.

A big field is a crowd: players at other tables who all share one stack. The recursion then
tracks which table players are placed but only HOW MANY of the crowd, which is still exact
Harville and prices hundreds of players.

Prizes are scaled so they add up to the chips in play. Values are then in chips too, and
winner-take-all ICM is exactly chip EV, which keeps the solver's units and stop rule the same.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from pushfold.spot import ALL_IN_EPSILON

MAX_PLAYERS = 20       # table plus field
MAX_SUBSETS = 200_000  # sets of placed players the recursion may walk: sum of C(players, k), k < paid
MAX_TRACKED = 12       # with a crowd: table plus field players tracked one by one
MAX_CROWD_WORK = 2**9 * 9 * 2_000  # with a crowd: subsets x tracked players x places paid


class PayoutError(ValueError):
    """A prize structure that cannot be priced. The message says what to fix."""


@dataclasses.dataclass(frozen=True)
class Payouts:
    prizes: tuple[float, ...]        # 1st, 2nd, ... in any currency; only the ratios matter
    field: tuple[float, ...] = ()    # stacks (bb) of players still in, at other tables
    crowd: int = 0                   # more players at other tables, each with crowd_stack (bb)
    crowd_stack: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "prizes", tuple(float(p) for p in self.prizes))
        object.__setattr__(self, "field", tuple(float(s) for s in self.field))
        if not self.prizes or not all(math.isfinite(p) and p >= 0 for p in self.prizes):
            raise PayoutError(f"prizes must be numbers >= 0, got {self.prizes}")
        if sum(self.prizes) <= 0:
            raise PayoutError("at least one prize must be above 0")
        if not all(math.isfinite(s) and s > 0 for s in self.field):
            raise PayoutError(f"field stacks must be positive numbers of big blinds, got {self.field}")
        if self.crowd < 0 or (self.crowd and not (math.isfinite(self.crowd_stack) and self.crowd_stack > 0)):
            raise PayoutError(f"a crowd needs a count >= 0 and a positive stack, got {self.crowd} "
                              f"x {self.crowd_stack}bb")

    @property
    def chips_away(self) -> float:
        """Chips at other tables."""
        return sum(self.field) + self.crowd * self.crowd_stack

    def check(self, table: int) -> None:
        tracked = table + len(self.field)
        players = tracked + self.crowd
        if len(self.prizes) > players:
            raise PayoutError(f"{len(self.prizes)} places paid but only {players} players left")
        if self.crowd:
            if tracked > MAX_TRACKED:
                raise PayoutError(f"{tracked} players tracked one by one; with a crowd at most {MAX_TRACKED}")
            if 2**tracked * tracked * len(self.prizes) > MAX_CROWD_WORK:
                raise PayoutError(f"{len(self.prizes)} places paid is too slow to price; pay fewer places")
            return
        if players > MAX_PLAYERS:
            raise PayoutError(f"{players} players left; ICM here handles at most {MAX_PLAYERS}")
        if sum(math.comb(players, k) for k in range(len(self.prizes))) > MAX_SUBSETS:
            raise PayoutError(f"{len(self.prizes)} places paid among {players} players is too slow "
                              "to price; pay fewer places or leave out part of the field")

    def scaled(self, chips: float) -> np.ndarray:
        prizes = np.array(self.prizes)
        return prizes * chips / prizes.sum()


def harville(stacks: np.ndarray, prizes: np.ndarray) -> np.ndarray:
    """Expected prize per player, one table per row: stacks (E, N) -> (E, N).

    Walks the sets of players who took the top places, one place at a time.
    A player with no chips never takes a place here.
    """
    stacks = np.asarray(stacks, dtype=float)
    rows, n = stacks.shape
    total = stacks.sum(axis=1)
    out = np.zeros((rows, n))
    paid = min(len(prizes), n)
    frontier = {0: np.ones(rows)}
    for place in range(paid):
        following: dict[int, np.ndarray] = {}
        for placed, chance in frontier.items():
            members = [i for i in range(n) if placed >> i & 1]
            left = total - stacks[:, members].sum(axis=1)
            share = np.divide(stacks, left[:, None], out=np.zeros_like(stacks),
                              where=left[:, None] > ALL_IN_EPSILON)
            share[:, members] = 0.0
            step = chance[:, None] * share
            out += prizes[place] * step
            if place + 1 == paid:
                continue
            for i in range(n):
                if not placed >> i & 1:
                    key = placed | 1 << i
                    following[key] = following.get(key, 0.0) + step[:, i]
        frontier = following
    return out


def crowd_harville(stacks: np.ndarray, prizes: np.ndarray, crowd: int, each: float) -> np.ndarray:
    """harville() for the first N players, plus `crowd` more who all hold `each` chips.

    State: which of the N are placed (a subset) and how many of the crowd, which is fixed by
    the place being filled. Every subset moves forward together, one place at a time.
    """
    stacks = np.asarray(stacks, dtype=float)
    rows, n = stacks.shape
    subsets = np.arange(1 << n)
    member = (subsets[:, None] >> np.arange(n) & 1).astype(bool)          # (2^n, n)
    size = member.sum(axis=1)
    placed_chips = member.astype(float) @ stacks.T                           # (2^n, rows)
    total = stacks.sum(axis=1) + crowd * each
    out = np.zeros((rows, n))
    chance = np.zeros((1 << n, rows))
    chance[0] = 1.0
    for place, prize in enumerate(prizes):
        taken = place - size                                                 # crowd already placed
        live = (taken >= 0) & (taken <= crowd)
        left = total[None, :] - placed_chips - (taken * each)[:, None]
        per_chip = np.divide(chance, left, out=np.zeros_like(chance),
                             where=live[:, None] & (left > ALL_IN_EPSILON))
        step = per_chip[:, :, None] * stacks[None, :, :] * ~member[:, None, :]  # (2^n, rows, n)
        out += prize * step.sum(axis=0)
        following = per_chip * (np.where(live, crowd - taken, 0) * each)[:, None]
        for i in range(n):
            before = subsets[~member[:, i]]
            following[before | 1 << i] += step[before, :, i]
        chance = following
    return out


def value(final: np.ndarray, start: tuple[float, ...], payouts: Payouts) -> np.ndarray:
    """ICM value in chips of each table seat's final stack: final (E, n) -> (E, n)."""
    final = np.where(np.abs(np.atleast_2d(final)) <= ALL_IN_EPSILON, 0.0, np.atleast_2d(final))
    rows, n = final.shape
    payouts.check(n)
    stacks = np.hstack([final, np.tile(np.array(payouts.field), (rows, 1))])
    prizes = payouts.scaled(sum(start) + payouts.chips_away)
    if payouts.crowd:
        out = crowd_harville(stacks, prizes, payouts.crowd, payouts.crowd_stack)
    else:
        out = harville(stacks, prizes)
    ladder = np.concatenate([prizes, np.zeros(stacks.shape[1] + payouts.crowd)])
    for row in np.nonzero((final <= 0).any(axis=1))[0]:
        place = int((stacks[row] > 0).sum()) + payouts.crowd
        busted = sorted(np.nonzero(final[row] <= 0)[0], key=lambda s: -start[s])
        for size in sorted({start[s] for s in busted}, reverse=True):
            group = [s for s in busted if start[s] == size]
            out[row, group] = ladder[place:place + len(group)].mean()
            place += len(group)
    return out[:, :n]
