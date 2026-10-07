"""Exact hi-lo equity features for O8 hands, fast enough to tabulate every turn and to run in the browser.

On a complete board every opponent hand's best high and low come from its six two-card pairs, so a
pair table (two cards x the board's ten triples) gives all 178,365 opponent hands cheaply. Their
(high, low) values go into count grids: one over all opponents and one per card for the opponents
holding that card. A hero's result against the opponents that do not share its cards is the total
grid minus its four cards' grids (first-order card removal: opponents holding two of the hero's cards
are taken out twice, ~5% of them). The same grids weighted by the strong range (ranges.py) give the
result against the hands that 3-bet.

Pot shares follow equity._shares in quarters of the pot, so every sum is an integer and the browser
(public/static/o8-river.js) reproduces each feature bit for bit:

    high = SH / 4N, low = SL / 4N, square = SQ / 16N, strong high = WH / 4W, strong low = WL / 4W

Turn and flop features average the river features over every river (and turn) card that is not on
the board or in the hand. Features: (high, low, spread) against a random hand, (high, low) against
the strong range, as pool.py.
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

from .evaluator import NO_LOW, high5, low5

WEIGHT_SCALE = 1_000_000  # strong-range weights as integers
FEATURES = 5


@njit(cache=True)  # pragma: no cover - compiled native code
def pair_tables(board: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best high (larger is better) and low (smaller, NO_LOW if none) of every two-card pair off the board."""
    hi = np.full((52, 52), -1, dtype=np.int64)
    lo = np.full((52, 52), NO_LOW, dtype=np.int64)
    on = np.zeros(52, dtype=np.bool_)
    for c in board:
        on[c] = True
    for a in range(52):
        if on[a]:
            continue
        for b in range(a + 1, 52):
            if on[b]:
                continue
            best_hi, best_lo = -1, NO_LOW
            for x in range(5):
                for y in range(x + 1, 5):
                    for z in range(y + 1, 5):
                        v = high5(a, b, board[x], board[y], board[z])
                        if v > best_hi:
                            best_hi = v
                        w = low5(a, b, board[x], board[y], board[z])
                        if w < best_lo:
                            best_lo = w
            hi[a, b] = hi[b, a] = best_hi
            lo[a, b] = lo[b, a] = best_lo
    return hi, lo


@njit(cache=True)  # pragma: no cover - compiled native code
def hand_value(cards: np.ndarray, hi: np.ndarray, lo: np.ndarray) -> tuple[int, int]:
    best_hi, best_lo = -1, NO_LOW
    for i in range(4):
        for j in range(i + 1, 4):
            if hi[cards[i], cards[j]] > best_hi:
                best_hi = hi[cards[i], cards[j]]
            if lo[cards[i], cards[j]] < best_lo:
                best_lo = lo[cards[i], cards[j]]
    return best_hi, best_lo


@njit(cache=True)  # pragma: no cover - compiled native code
def _grids(board: np.ndarray, hi: np.ndarray, lo: np.ndarray, weights: np.ndarray, colex: np.ndarray):
    """Opponent grids over (high index, low index): counts and strong weights, total (row 52) and per card.

    Returns the sorted distinct highs and lows of the opponents and prefix-summed grids of shape
    (53, highs + 1, lows + 1) so a rectangle is four lookups."""
    live = np.empty(47, dtype=np.int64)
    n = 0
    on = np.zeros(52, dtype=np.bool_)
    for c in board:
        on[c] = True
    for c in range(52):
        if not on[c]:
            live[n] = c
            n += 1
    count = 178365  # C(47, 4)
    opp_hi = np.empty(count, dtype=np.int64)
    opp_lo = np.empty(count, dtype=np.int64)
    opp_cards = np.empty((count, 4), dtype=np.int64)
    k = 0
    hand = np.empty(4, dtype=np.int64)
    for a in range(47):
        for b in range(a + 1, 47):
            for c in range(b + 1, 47):
                for d in range(c + 1, 47):
                    hand[0], hand[1], hand[2], hand[3] = live[a], live[b], live[c], live[d]
                    opp_hi[k], opp_lo[k] = hand_value(hand, hi, lo)
                    opp_cards[k] = hand
                    k += 1
    highs = np.unique(opp_hi)
    lows = np.unique(opp_lo)  # NO_LOW, if present, sorts last
    nh, nl = highs.shape[0], lows.shape[0]
    counts = np.zeros((53, nh + 1, nl + 1), dtype=np.int64)
    strong = np.zeros((53, nh + 1, nl + 1), dtype=np.int64)
    for k in range(count):
        i = np.searchsorted(highs, opp_hi[k]) + 1
        j = np.searchsorted(lows, opp_lo[k]) + 1
        c0, c1, c2, c3 = opp_cards[k, 0], opp_cards[k, 1], opp_cards[k, 2], opp_cards[k, 3]
        w = weights[colex[c0, c1, c2, c3]]
        for g in (52, c0, c1, c2, c3):
            counts[g, i, j] += 1
            strong[g, i, j] += w
    for g in range(53):
        for i in range(1, nh + 1):
            for j in range(1, nl + 1):
                counts[g, i, j] += counts[g, i - 1, j] + counts[g, i, j - 1] - counts[g, i - 1, j - 1]
                strong[g, i, j] += strong[g, i - 1, j] + strong[g, i, j - 1] - strong[g, i - 1, j - 1]
    return highs, lows, counts, strong


@njit(cache=True)  # pragma: no cover - compiled native code
def _rect(grid: np.ndarray, g: int, i0: int, i1: int, j0: int, j1: int) -> int:
    """Sum over high indices [i0, i1) and low indices [j0, j1) of grid g (prefix-summed)."""
    if i1 <= i0 or j1 <= j0:
        return 0
    return grid[g, i1, j1] - grid[g, i0, j1] - grid[g, i1, j0] + grid[g, i0, j0]


@njit(cache=True)  # pragma: no cover - compiled native code
def _sums(g: int, my_hi: int, my_lo: int, highs, lows, counts, strong, out: np.ndarray) -> None:
    """Add grid g's (N, SH, SL, SQ, W, WH, WL) against a hero with (my_hi, my_lo) to ``out`` (all in quarters)."""
    nh, nl = highs.shape[0], lows.shape[0]
    h_less = np.searchsorted(highs, my_hi)  # opponents with a weaker high: [0, h_less)
    h_more = np.searchsorted(highs, my_hi, side="right")  # [h_less, h_more) tie, [h_more, nh) stronger
    has_none = nl > 0 and lows[nl - 1] == NO_LOW
    real = nl - 1 if has_none else nl  # low indices [0, real) hold real lows
    # high outcome in quarters of the whole pot when nobody has a low: win 4, tie 2, lose 0
    spans = np.array([[0, h_less, 4], [h_less, h_more, 2], [h_more, nh, 0]])
    groups = np.zeros((4, 4), dtype=np.int64)  # low index range [j0, j1), high-share divisor, low quarters
    if my_lo == NO_LOW:
        rows = 2
        groups[0] = (real, nl, 1, 0)  # opponent has no low either: the whole pot goes by the high
        groups[1] = (0, real, 2, 0)   # opponent has a low: half by the high, the low half is theirs
    else:
        rows = 4
        l_less = np.searchsorted(lows, my_lo)  # better lows [0, l_less), equal, worse up to real
        l_more = np.searchsorted(lows, my_lo, side="right")
        groups[0] = (0, l_less, 2, 0)
        groups[1] = (l_less, l_more, 2, 1)
        groups[2] = (l_more, real, 2, 2)
        groups[3] = (real, nl, 2, 2)
    for s in range(3):
        i0, i1, win = spans[s, 0], spans[s, 1], spans[s, 2]
        if i1 <= i0:
            continue
        for q in range(rows):
            j0, j1, hq, lq = groups[q, 0], groups[q, 1], win // groups[q, 2], groups[q, 3]
            n = _rect(counts, g, i0, i1, j0, j1)
            w = _rect(strong, g, i0, i1, j0, j1)
            out[0] += n
            out[1] += n * hq
            out[2] += n * lq
            out[3] += n * (hq + lq) * (hq + lq)
            out[4] += w
            out[5] += w * hq
            out[6] += w * lq


@njit(cache=True)  # pragma: no cover - compiled native code
def river_sums(board: np.ndarray, hands: np.ndarray, weights: np.ndarray, colex: np.ndarray) -> np.ndarray:
    """(n, 7) integer sums (N, SH, SL, SQ, W, WH, WL) for every hand; rows of hands that touch the board are 0."""
    hi, lo = pair_tables(board)
    highs, lows, counts, strong = _grids(board, hi, lo, weights, colex)
    on = np.zeros(52, dtype=np.bool_)
    for c in board:
        on[c] = True
    n = hands.shape[0]
    out = np.zeros((n, 7), dtype=np.int64)
    total = np.zeros(7, dtype=np.int64)
    part = np.zeros(7, dtype=np.int64)
    for k in range(n):
        h = hands[k]
        if on[h[0]] or on[h[1]] or on[h[2]] or on[h[3]]:
            continue
        my_hi, my_lo = hand_value(h, hi, lo)
        total[:] = 0
        _sums(52, my_hi, my_lo, highs, lows, counts, strong, total)
        for c in range(4):
            part[:] = 0
            _sums(h[c], my_hi, my_lo, highs, lows, counts, strong, part)
            total -= part
        out[k] = total
    return out


@njit(cache=True)  # pragma: no cover - compiled native code
def river_sums_fast(board: np.ndarray, hands: np.ndarray, weights: np.ndarray, colex: np.ndarray) -> np.ndarray:
    """river_sums, computed once per distinct (high, low) of the hands and per grid, then added up per hand."""
    hi, lo = pair_tables(board)
    highs, lows, counts, strong = _grids(board, hi, lo, weights, colex)
    on = np.zeros(52, dtype=np.bool_)
    for c in board:
        on[c] = True
    n = hands.shape[0]
    my_hi = np.full(n, -1, dtype=np.int64)
    my_lo = np.zeros(n, dtype=np.int64)
    for k in range(n):
        h = hands[k]
        if not (on[h[0]] or on[h[1]] or on[h[2]] or on[h[3]]):
            my_hi[k], my_lo[k] = hand_value(h, hi, lo)
    key = my_hi * (NO_LOW + 1) + my_lo
    distinct, which = np.unique(key[my_hi >= 0]), np.full(n, -1, dtype=np.int64)
    valid = np.flatnonzero(my_hi >= 0)
    which[valid] = np.searchsorted(distinct, key[valid])
    table = np.zeros((53, distinct.shape[0], 7), dtype=np.int64)
    for d in range(distinct.shape[0]):
        v_hi, v_lo = distinct[d] // (NO_LOW + 1), distinct[d] % (NO_LOW + 1)
        for g in range(53):
            if g == 52 or not on[g]:
                _sums(g, v_hi, v_lo, highs, lows, counts, strong, table[g, d])
    out = np.zeros((n, 7), dtype=np.int64)
    for k in valid:
        d = which[k]
        h = hands[k]
        for m in range(7):
            out[k, m] = table[52, d, m] - table[h[0], d, m] - table[h[1], d, m] - table[h[2], d, m] - table[h[3], d, m]
    return out


@njit(cache=True)  # pragma: no cover - compiled native code
def features_from_sums(s: np.ndarray) -> np.ndarray:
    """(high, low, mean square of pot share, strong high, strong low) from river_sums rows."""
    out = np.zeros((s.shape[0], 5))
    for k in range(s.shape[0]):
        if s[k, 0] <= 0:
            continue
        out[k, 0] = s[k, 1] / (4.0 * s[k, 0])
        out[k, 1] = s[k, 2] / (4.0 * s[k, 0])
        out[k, 2] = s[k, 3] / (16.0 * s[k, 0])
        if s[k, 4] > 0:
            out[k, 3] = s[k, 5] / (4.0 * s[k, 4])
            out[k, 4] = s[k, 6] / (4.0 * s[k, 4])
    return out


def colex_table() -> np.ndarray:
    """Index of a sorted four-card hand in combinations(range(52), 4) order, as a dense 52^4 table."""
    import itertools
    table = np.full((52, 52, 52, 52), -1, dtype=np.int32)
    for i, (a, b, c, d) in enumerate(itertools.combinations(range(52), 4)):
        table[a, b, c, d] = i
    return table


def strong_weights(path=None) -> np.ndarray:
    from .ranges import RANGE
    weights = np.load(path or RANGE)["weights"].astype(np.float64)
    return np.rint(weights * WEIGHT_SCALE).astype(np.int64)
