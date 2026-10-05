"""Native Omaha high and 8-or-better low evaluation.

high5: larger is stronger. low5: smaller is better, NO_LOW when the five cards do not qualify.
Omaha hands use exactly two hole cards and three board cards for each half.
"""

from __future__ import annotations

import itertools
import math

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


# Table-driven evaluation for many hands against one board (equity sampling). prepare_board does the
# board's share once; each hand then costs a merge and a table lookup per hole pair and board triple.
# Values are identical to omaha_high / omaha_low.
_BINOM = np.array([[math.comb(n, k) for k in range(6)] for n in range(18)], dtype=np.int64)


def _multiset_index(ranks: tuple[int, ...]) -> int:
    """Index of five ascending ranks (repeats allowed) among the C(17, 5) multisets."""
    return sum(math.comb(r + i, i + 1) for i, r in enumerate(ranks))


def _rank_tables() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    plain = np.zeros(math.comb(17, 5), dtype=np.int64)
    for ranks in itertools.combinations_with_replacement(range(13), 5):
        if max(ranks.count(r) for r in ranks) <= 4:
            suits = [0] * 5
            for i in range(1, 5):  # rotate suits so five cards never share one and no card repeats
                suits[i] = (suits[i - 1] + 1) % 4 if ranks[i] == ranks[i - 1] else (1 if i == 1 else 0)
            cards = [r * 4 + s for r, s in zip(ranks, suits)]
            plain[_multiset_index(ranks)] = high5(*cards)
    flush = np.zeros(1 << 13, dtype=np.int64)
    for ranks in itertools.combinations(range(13), 5):
        flush[sum(1 << r for r in ranks)] = high5(*[r * 4 for r in ranks])
    low = np.full(1 << 9, NO_LOW, dtype=np.int64)
    for values in itertools.combinations(range(1, 9), 5):
        code = 0
        for v in sorted(values, reverse=True):
            code = code * 9 + v
        low[sum(1 << v for v in values)] = code
    return plain, flush, low


PLAIN5, FLUSH5, LOW5 = _rank_tables()


@njit(cache=True)
def prepare_board(board: np.ndarray, ranks: np.ndarray, suit: np.ndarray, mask: np.ndarray,
                  low: np.ndarray) -> None:
    """Fill per-triple tables for a complete board: ascending ranks (10, 3), common suit or -1, rank
    bitmask, and low bitmask (bit v for low value v) or -1 when the triple has no three distinct lows."""
    for t in range(BOARD_TRIPLES.shape[0]):
        a, b, c = board[BOARD_TRIPLES[t, 0]], board[BOARD_TRIPLES[t, 1]], board[BOARD_TRIPLES[t, 2]]
        x, y, z = a >> 2, b >> 2, c >> 2
        if x > y:
            x, y = y, x
        if y > z:
            y, z = z, y
        if x > y:
            x, y = y, x
        ranks[t, 0], ranks[t, 1], ranks[t, 2] = x, y, z
        suit[t] = a & 3 if (a & 3) == (b & 3) and (a & 3) == (c & 3) else -1
        mask[t] = (1 << x) | (1 << y) | (1 << z)
        la, lb, lc = _low_value(a), _low_value(b), _low_value(c)
        lm = (1 << la) | (1 << lb) | (1 << lc)
        low[t] = lm if la and lb and lc and la != lb and la != lc and lb != lc else -1


@njit(cache=True)
def omaha_high_prepared(hole: np.ndarray, ranks: np.ndarray, suit: np.ndarray, mask: np.ndarray,
                        plain: np.ndarray, flush: np.ndarray) -> int:
    best = -1
    m = np.empty(5, dtype=np.int64)
    for p in range(HOLE_PAIRS.shape[0]):
        a, b = hole[HOLE_PAIRS[p, 0]], hole[HOLE_PAIRS[p, 1]]
        u, v = a >> 2, b >> 2
        if u > v:
            u, v = v, u
        pair_suit = a & 3 if (a & 3) == (b & 3) else -2
        for t in range(BOARD_TRIPLES.shape[0]):
            if suit[t] == pair_suit:
                value = flush[mask[t] | (1 << u) | (1 << v)]
            else:
                i = j = 0
                for k in range(5):  # merge the pair into the triple, ascending
                    if j == 3 or (i < 2 and (u if i == 0 else v) <= ranks[t, j]):
                        m[k] = u if i == 0 else v
                        i += 1
                    else:
                        m[k] = ranks[t, j]
                        j += 1
                index = 0
                for k in range(5):
                    index += _BINOM[m[k] + k, k + 1]
                value = plain[index]
            if value > best:
                best = value
    return best


@njit(cache=True)
def omaha_low_prepared(hole: np.ndarray, low: np.ndarray, table: np.ndarray) -> int:
    best = NO_LOW
    for p in range(HOLE_PAIRS.shape[0]):
        la, lb = _low_value(hole[HOLE_PAIRS[p, 0]]), _low_value(hole[HOLE_PAIRS[p, 1]])
        if la == 0 or lb == 0 or la == lb:
            continue
        pm = (1 << la) | (1 << lb)
        for t in range(BOARD_TRIPLES.shape[0]):
            if low[t] >= 0 and (low[t] & pm) == 0:
                value = table[low[t] | pm]
                if value < best:
                    best = value
    return best
