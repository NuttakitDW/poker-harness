"""Hi-lo equity of an Omaha 8 hand against one random opponent hand.

Equity is split into the two halves of the pot: `high` is the expected share won through the high
hand (the whole pot when nobody has a low), `low` the expected share won through the low (at most
one half). Their sum is the expected share of the pot. `square` is the mean squared final share,
which with the mean describes how spread out the outcome still is (draws versus made hands).
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

from .evaluator import (FLUSH5, LOW5, NO_LOW, PLAIN5, omaha_high, omaha_high_prepared, omaha_low,
                        omaha_low_prepared, prepare_board)


@njit(cache=True)
def _shares(my_hi: int, my_lo: int, opp_hi: int, opp_lo: int) -> tuple[float, float]:
    h = 1.0 if my_hi > opp_hi else 0.5 if my_hi == opp_hi else 0.0
    if my_lo == NO_LOW and opp_lo == NO_LOW:
        return h, 0.0
    lo = 1.0 if my_lo < opp_lo else 0.5 if my_lo == opp_lo else 0.0
    return 0.5 * h, 0.5 * lo


@njit(cache=True)
def _live_cards(hole: np.ndarray, board: np.ndarray, known: int) -> np.ndarray:
    dead = np.zeros(52, dtype=np.bool_)
    for c in hole:
        dead[c] = True
    for i in range(known):
        dead[board[i]] = True
    live = np.empty(52 - 4 - known, dtype=np.int64)
    k = 0
    for c in range(52):
        if not dead[c]:
            live[k] = c
            k += 1
    return live


@njit(cache=True)
def hand_equity(hole: np.ndarray, board: np.ndarray, known: int, runouts: int, opponents: int,
                seed: int) -> tuple[float, float, float]:
    """Sampled (high, low, mean square of pot share) given the first `known` board cards.

    Each of `runouts` random board completions is evaluated once for us and against `opponents`
    random opponent hands drawn from the cards that are left.
    """
    np.random.seed(seed)
    live = _live_cards(hole, board, known)
    full = np.empty(5, dtype=np.int64)
    for i in range(known):
        full[i] = board[i]
    need = 5 - known
    hi_sum = lo_sum = sq_sum = 0.0
    for _ in range(runouts):
        # Partial shuffle: the first `need` live cards finish the board, the next four are an opponent.
        for i in range(need):
            j = i + np.random.randint(len(live) - i)
            live[i], live[j] = live[j], live[i]
            full[known + i] = live[i]
        my_hi, my_lo = omaha_high(hole, full), omaha_low(hole, full)
        for _ in range(opponents):
            for i in range(need, need + 4):
                j = i + np.random.randint(len(live) - i)
                live[i], live[j] = live[j], live[i]
            opp = live[need:need + 4]
            h, lo = _shares(my_hi, my_lo, omaha_high(opp, full), omaha_low(opp, full))
            hi_sum += h
            lo_sum += lo
            sq_sum += (h + lo) * (h + lo)
    n = runouts * opponents
    return hi_sum / n, lo_sum / n, sq_sum / n


FEATURES = 5  # high, low, spread against a random hand; high, low against the strong range
MAX_TRIES = 10_000


@njit(cache=True)
def range_hand(combos: np.ndarray, cdf: np.ndarray, dead: np.ndarray, out: np.ndarray) -> bool:
    """Draw a hand from the weighted range (cumulative weights `cdf` over `combos`) that avoids the
    dead cards. Rejection keeps the draw exact under card removal; False if none was found."""
    total = cdf[-1]
    for _ in range(MAX_TRIES):
        i = min(np.searchsorted(cdf, np.random.random() * total, side="right"), cdf.shape[0] - 1)
        if not (dead[combos[i, 0]] or dead[combos[i, 1]] or dead[combos[i, 2]] or dead[combos[i, 3]]):
            for k in range(4):
                out[k] = combos[i, k]
            return True
    return False


@njit(cache=True)
def hand_features(hole: np.ndarray, board: np.ndarray, known: int, runouts: int, opponents: int,
                  strong: int, combos: np.ndarray, cdf: np.ndarray, seed: int) -> np.ndarray:
    """FEATURES numbers for a hand given the first `known` board cards: (high, low, spread) against a
    random hand as in hand_equity, then (high, low) against `strong` hands per runout drawn from the
    strong range. Two hands with the same score against a random hand, such as a bare nut low draw
    and a middling two pair, can be far apart against the hands that reach a raised pot."""
    np.random.seed(seed)
    live = _live_cards(hole, board, known)
    full = np.empty(5, dtype=np.int64)
    for i in range(known):
        full[i] = board[i]
    need = 5 - known
    dead = np.zeros(52, dtype=np.bool_)
    opp = np.empty(4, dtype=np.int64)
    ranks = np.empty((10, 3), dtype=np.int64)
    suit = np.empty(10, dtype=np.int64)
    mask = np.empty(10, dtype=np.int64)
    low = np.empty(10, dtype=np.int64)
    hi_sum = lo_sum = sq_sum = s_hi = s_lo = 0.0
    s_n = 0
    for _ in range(runouts):
        for i in range(need):
            j = i + np.random.randint(len(live) - i)
            live[i], live[j] = live[j], live[i]
            full[known + i] = live[i]
        prepare_board(full, ranks, suit, mask, low)
        my_hi = omaha_high_prepared(hole, ranks, suit, mask, PLAIN5, FLUSH5)
        my_lo = omaha_low_prepared(hole, low, LOW5)
        for _ in range(opponents):
            for i in range(need, need + 4):
                j = i + np.random.randint(len(live) - i)
                live[i], live[j] = live[j], live[i]
                opp[i - need] = live[i]
            h, lo = _shares(my_hi, my_lo, omaha_high_prepared(opp, ranks, suit, mask, PLAIN5, FLUSH5),
                            omaha_low_prepared(opp, low, LOW5))
            hi_sum += h
            lo_sum += lo
            sq_sum += (h + lo) * (h + lo)
        dead[:] = False
        for c in hole:
            dead[c] = True
        for c in full:
            dead[c] = True
        for _ in range(strong):
            if range_hand(combos, cdf, dead, opp):
                h, lo = _shares(my_hi, my_lo, omaha_high_prepared(opp, ranks, suit, mask, PLAIN5, FLUSH5),
                                omaha_low_prepared(opp, low, LOW5))
                s_hi += h
                s_lo += lo
                s_n += 1
    n = runouts * opponents
    out = np.empty(FEATURES, dtype=np.float64)
    out[0], out[1] = hi_sum / n, lo_sum / n
    mean = out[0] + out[1]
    out[2] = np.sqrt(max(sq_sum / n - mean * mean, 0.0))
    out[3] = s_hi / s_n if s_n else out[0]
    out[4] = s_lo / s_n if s_n else out[1]
    return out


@njit(cache=True)
def exact_river(hole: np.ndarray, board: np.ndarray) -> tuple[float, float]:
    """Exact (high, low) against every opponent hand on a complete board."""
    live = _live_cards(hole, board, 5)
    my_hi, my_lo = omaha_high(hole, board), omaha_low(hole, board)
    opp = np.empty(4, dtype=np.int64)
    hi_sum = lo_sum = 0.0
    n = 0
    m = len(live)
    for a in range(m):
        for b in range(a + 1, m):
            for c in range(b + 1, m):
                for d in range(c + 1, m):
                    opp[0], opp[1], opp[2], opp[3] = live[a], live[b], live[c], live[d]
                    h, lo = _shares(my_hi, my_lo, omaha_high(opp, board), omaha_low(opp, board))
                    hi_sum += h
                    lo_sum += lo
                    n += 1
    return hi_sum / n, lo_sum / n


@njit(cache=True, parallel=True)
def preflop_table(hands: np.ndarray, runouts: int, opponents: int, seed: int) -> np.ndarray:
    """(high, low, square) for each row of `hands` (n, 4) with no board known."""
    out = np.empty((hands.shape[0], 3))
    board = np.zeros(5, dtype=np.int64)
    for i in prange(hands.shape[0]):
        out[i, 0], out[i, 1], out[i, 2] = hand_equity(hands[i], board, 0, runouts, opponents, seed + i)
    return out
