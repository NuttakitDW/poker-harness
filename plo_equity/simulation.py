"""Deterministic fixed-block Monte Carlo samples for one physical PLO4 hand."""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable
from dataclasses import dataclass

from .cards import DECK_SIZE, canonical_hand, class_key
from .evaluator import _evaluate_unchecked

BLOCK_SIZE = 1_000
RNG_VERSION = "sha256-python-random-sample-v1"


@dataclass(frozen=True)
class TrialStats:
    n: int = 0
    sum_x: float = 0.0
    sum_x2: float = 0.0
    wins: int = 0
    ties: int = 0

    def __post_init__(self):
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in (self.n, self.wins, self.ties)):
            raise ValueError("n, wins, and ties must be integers")
        if self.n < 0 or self.wins < 0 or self.ties < 0 or self.wins + self.ties > self.n:
            raise ValueError("trial counts are inconsistent")
        if not math.isfinite(self.sum_x) or not math.isfinite(self.sum_x2):
            raise ValueError("trial moments must be finite")
        if not 0 <= self.sum_x <= self.n or not 0 <= self.sum_x2 <= self.n:
            raise ValueError("trial moments must be within outcome bounds")
        if self.n and self.sum_x2 + 1e-12 < self.sum_x * self.sum_x / self.n:
            raise ValueError("second moment is inconsistent with the mean")

    def __add__(self, other: TrialStats) -> TrialStats:
        return TrialStats(self.n + other.n, self.sum_x + other.sum_x,
                          self.sum_x2 + other.sum_x2, self.wins + other.wins,
                          self.ties + other.ties)

    @property
    def equity(self) -> float:
        return self.sum_x / self.n if self.n else float("nan")

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else float("nan")

    @property
    def tie_rate(self) -> float:
        return self.ties / self.n if self.n else float("nan")

    @property
    def standard_error(self) -> float:
        if self.n < 2:
            return float("nan")
        variance = max(0.0, (self.sum_x2 - self.sum_x * self.sum_x / self.n) / (self.n - 1))
        return math.sqrt(variance / self.n)


def _block_seed(hero: tuple[int, ...], global_seed: int, block_index: int,
                opponents: int) -> int:
    payload = f"{RNG_VERSION}|{global_seed}|{class_key(hero)}|{opponents}|{block_index}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "big")


def deal_block(hero: Iterable[int], global_seed: int, block_index: int,
               opponents: int = 1) -> tuple[tuple[int, ...], ...]:
    hero = canonical_hand(hero)
    if not 1 <= opponents <= 5:
        raise ValueError("opponents must be from 1 through 5")
    needed = 5 + 4 * opponents
    remaining = tuple(card for card in range(DECK_SIZE) if card not in hero)
    rng = random.Random(_block_seed(hero, global_seed, block_index, opponents))
    return tuple(tuple(rng.sample(remaining, needed)) for _ in range(BLOCK_SIZE))


def _trial(hero: tuple[int, ...], dealt: tuple[int, ...], opponents: int) -> tuple[float, int, int]:
    board = dealt[:5]
    hero_score = _evaluate_unchecked(hero, board)
    scores = [hero_score]
    for seat in range(opponents):
        start = 5 + seat * 4
        scores.append(_evaluate_unchecked(dealt[start:start + 4], board))
    best = min(scores)
    if hero_score != best:
        return 0.0, 0, 0
    winners = scores.count(best)
    return 1.0 / winners, int(winners == 1), int(winners > 1)


def simulate_range(hero: Iterable[int], start: int, stop: int, global_seed: int,
                   opponents: int = 1) -> TrialStats:
    hero = canonical_hand(hero)
    if not 0 <= start <= stop:
        raise ValueError("sample range must satisfy 0 <= start <= stop")
    n = 0
    sum_x = sum_x2 = 0.0
    wins = ties = 0
    cursor = start
    while cursor < stop:
        block_index, offset = divmod(cursor, BLOCK_SIZE)
        end = min(stop, (block_index + 1) * BLOCK_SIZE)
        deals = deal_block(hero, global_seed, block_index, opponents)
        for dealt in deals[offset:offset + end - cursor]:
            share, win, tie = _trial(hero, dealt, opponents)
            n += 1
            sum_x += share
            sum_x2 += share * share
            wins += win
            ties += tie
        cursor = end
    return TrialStats(n, sum_x, sum_x2, wins, ties)
