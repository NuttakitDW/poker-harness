"""Hi-lo equity of an Omaha 8 hand against one random opponent hand.

Equity is split into the two halves of the pot: `high` is the expected share won through the high
hand (the whole pot when nobody has a low), `low` the expected share won through the low (at most
one half). Their sum is the expected share of the pot. `square` is the mean squared final share,
which with the mean describes how spread out the outcome still is (draws versus made hands).
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

from .evaluator import NO_LOW, omaha_high, omaha_low


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
