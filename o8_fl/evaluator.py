"""Native Omaha high and 8-or-better low evaluation.

high5: larger is stronger. low5: smaller is better, NO_LOW when the five cards do not qualify.
Omaha hands use exactly two hole cards and three board cards for each half.
"""

from __future__ import annotations

import numpy as np
from numba import njit

BASE = 13
NO_LOW = 9 ** 5
HOLE_PAIRS = np.array([(a, b) for a in range(4) for b in range(a + 1, 4)], dtype=np.int64)
BOARD_TRIPLES = np.array([(a, b, c) for a in range(5) for b in range(a + 1, 5) for c in range(b + 1, 5)],
                         dtype=np.int64)
# Categories, weakest first.
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)


@njit(cache=True)
def straight_top(mask: int) -> int:
    """Highest straight top in a rank bitmask, or -1. The wheel A-2-3-4-5 tops at 5 (rank 3)."""
    for top in range(12, 3, -1):
        window = 0b11111 << (top - 4)
        if mask & window == window:
            return top
    wheel = (1 << 12) | 0b1111
    return 3 if mask & wheel == wheel else -1


@njit(cache=True)
def high5(c0: int, c1: int, c2: int, c3: int, c4: int) -> int:
    # Three bits of count per rank packed into one integer: no allocation in the hot path.
    packed = (1 << 3 * (c0 >> 2)) + (1 << 3 * (c1 >> 2)) + (1 << 3 * (c2 >> 2)) + (1 << 3 * (c3 >> 2)) \
        + (1 << 3 * (c4 >> 2))
    suit = c0 & 3
    flush = (c1 & 3) == suit and (c2 & 3) == suit and (c3 & 3) == suit and (c4 & 3) == suit
    mask = 0
    distinct = 0
    for r in range(13):
        if (packed >> 3 * r) & 7:
            mask |= 1 << r
            distinct += 1
    if distinct == 5:
        top = straight_top(mask)
        if top >= 0:
            return (STRAIGHT_FLUSH if flush else STRAIGHT) * BASE ** 5 + top
    value = 0
    max_count = 0
    pairs = 0
    for count in range(4, 0, -1):
        for r in range(12, -1, -1):
            if (packed >> 3 * r) & 7 == count:
                value = value * BASE + r
                if count > max_count:
                    max_count = count
                if count == 2:
                    pairs += 1
    for _ in range(distinct, 5):
        value = value * BASE
    if flush:
        category = FLUSH
    elif max_count == 4:
        category = QUADS
    elif max_count == 3:
        category = FULL_HOUSE if pairs == 1 else TRIPS
    elif pairs == 2:
        category = TWO_PAIR
    elif pairs == 1:
        category = PAIR
    else:
        category = HIGH_CARD
    return category * BASE ** 5 + value


@njit(cache=True)
def _low_value(card: int) -> int:
    rank = card >> 2
    if rank == 12:
        return 1
    if rank <= 6:
        return rank + 2
    return 0


@njit(cache=True)
def low5(c0: int, c1: int, c2: int, c3: int, c4: int) -> int:
    mask = 0
    for card in (c0, c1, c2, c3, c4):
        v = _low_value(card)
        if v == 0 or (mask >> v) & 1:
            return NO_LOW
        mask |= 1 << v
    code = 0
    for v in range(8, 0, -1):
        if (mask >> v) & 1:
            code = code * 9 + v
    return code


@njit(cache=True)
def omaha_high(hole: np.ndarray, board: np.ndarray) -> int:
    best = -1
    for p in range(HOLE_PAIRS.shape[0]):
        a, b = hole[HOLE_PAIRS[p, 0]], hole[HOLE_PAIRS[p, 1]]
        for t in range(BOARD_TRIPLES.shape[0]):
            v = high5(a, b, board[BOARD_TRIPLES[t, 0]], board[BOARD_TRIPLES[t, 1]], board[BOARD_TRIPLES[t, 2]])
            if v > best:
                best = v
    return best


@njit(cache=True)
def omaha_low(hole: np.ndarray, board: np.ndarray) -> int:
    best = NO_LOW
    for p in range(HOLE_PAIRS.shape[0]):
        a, b = hole[HOLE_PAIRS[p, 0]], hole[HOLE_PAIRS[p, 1]]
        if _low_value(a) == 0 or _low_value(b) == 0:
            continue
        for t in range(BOARD_TRIPLES.shape[0]):
            v = low5(a, b, board[BOARD_TRIPLES[t, 0]], board[BOARD_TRIPLES[t, 1]], board[BOARD_TRIPLES[t, 2]])
            if v < best:
                best = v
    return best
