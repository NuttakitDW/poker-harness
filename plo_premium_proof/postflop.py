"""Postflop information buckets: board-relative strength, flush draw, straight outs.

Strength is the fraction of all two-card holdings (from cards not on the board)
whose best Omaha hand beats hero's; it is computed once per board and street.
Flop/turn buckets = 10 strength bins x 3 flush-draw states x 4 straight-out
classes (120); river buckets = 10 strength bins.
"""

from __future__ import annotations

import numpy as np
from numba import njit


STRENGTH_EDGES = np.asarray([0.0, 0.001, 0.01, 0.03, 0.06, 0.12, 0.2, 0.3, 0.5], dtype=np.float64)
STRAIGHT_OR_BETTER = 1609  # phevaluator: ranks <= 1609 are straights or better
WHEEL = (1 << 12) | 0b1111


@njit(cache=True)  # pragma: no cover - compiled native code
def _merged_rank(p: int, q: int, x: int, y: int, z: int, rank5: np.ndarray, comb: np.ndarray) -> int:
    """Rank of five cards given sorted pairs ``p < q`` and ``x < y < z`` (no allocation)."""
    index = 0
    slot = 1
    i = 0
    j = 0
    while slot <= 5:
        take_pair = False
        if i < 2 and j < 3:
            a = p if i == 0 else q
            b = x if j == 0 else (y if j == 1 else z)
            take_pair = a < b
        elif i < 2:
            take_pair = True
        if take_pair:
            card = p if i == 0 else q
            i += 1
        else:
            card = x if j == 0 else (y if j == 1 else z)
            j += 1
        index += comb[card, slot]
        slot += 1
    return rank5[index]


@njit(cache=True)  # pragma: no cover - compiled native code
def _sorted_copy(cards: np.ndarray, count: int) -> np.ndarray:
    out = cards[:count].copy()
    out.sort()
    return out


@njit(cache=True)  # pragma: no cover - compiled native code
def best_rank(hole: np.ndarray, board: np.ndarray, shown: int, rank5: np.ndarray, comb: np.ndarray) -> int:
    """Best Omaha rank with exactly two of the ``hole`` cards and three of ``shown`` board cards."""
    cards = _sorted_copy(hole, hole.size)
    table = _sorted_copy(board, shown)
    best = 1 << 30
    for i in range(cards.size):
        for j in range(i + 1, cards.size):
            for x in range(shown):
                for y in range(x + 1, shown):
                    for z in range(y + 1, shown):
                        rank = _merged_rank(cards[i], cards[j], table[x], table[y], table[z], rank5, comb)
                        if rank < best:
                            best = rank
    return best


@njit(cache=True)  # pragma: no cover - compiled native code
def board_distribution(board: np.ndarray, shown: int, rank5: np.ndarray, comb: np.ndarray,
                       out: np.ndarray) -> int:
    """Sorted best ranks of every two-card holding on this board; returns the count."""
    count = 0
    table = _sorted_copy(board, shown)
    for a in range(52):
        if _on_board(a, board, shown):
            continue
        for b in range(a + 1, 52):
            if _on_board(b, board, shown):
                continue
            best = 1 << 30
            for x in range(shown):
                for y in range(x + 1, shown):
                    for z in range(y + 1, shown):
                        rank = _merged_rank(a, b, table[x], table[y], table[z], rank5, comb)
                        if rank < best:
                            best = rank
            out[count] = best
            count += 1
    out[:count].sort()
    return count


@njit(cache=True)  # pragma: no cover - compiled native code
def _on_board(card: int, board: np.ndarray, shown: int) -> bool:
    for k in range(shown):
        if board[k] == card:
            return True
    return False


@njit(cache=True)  # pragma: no cover - compiled native code
def strength_bin(rank: int, distribution: np.ndarray, count: int) -> int:
    """0 = nothing beats it (nut) ... 9 = more than half of holdings beat it."""
    better = np.searchsorted(distribution[:count], rank)  # strictly lower rank = stronger
    fraction = better / count
    if better == 0:
        return 0
    for index in range(1, STRENGTH_EDGES.size):
        if fraction <= STRENGTH_EDGES[index]:
            return index
    return STRENGTH_EDGES.size


@njit(cache=True)  # pragma: no cover - compiled native code
def flush_draw(hole: np.ndarray, board: np.ndarray, shown: int) -> int:
    """0 none, 1 non-nut draw, 2 nut draw: two hole cards to a suit with two on board."""
    best = 0
    for suit in range(4):
        on_board = 0
        for k in range(shown):
            if board[k] % 4 == suit:
                on_board += 1
        mine = 0
        for card in hole:
            if card % 4 == suit:
                mine += 1
        if on_board != 2 or mine < 2:
            continue
        state = 1
        for rank in range(12, -1, -1):
            card = rank * 4 + suit
            if _on_board(card, board, shown):
                continue
            for held in hole:
                if held == card:
                    state = 2
            break
        if state > best:
            best = state
    return best


@njit(cache=True)  # pragma: no cover - compiled native code
def _is_straight(mask: int) -> bool:
    if mask == WHEEL:
        return True
    low = mask & -mask
    return mask == low * 0b11111


@njit(cache=True)  # pragma: no cover - compiled native code
def straight_out_ranks(hole: np.ndarray, board: np.ndarray, shown: int) -> int:
    """Number of distinct next-card ranks that would give hero a straight."""
    outs = 0
    held = hole.shape[0]
    for rank in range(13):
        found = False
        for i in range(held):
            for j in range(i + 1, held):
                if found:
                    break
                for x in range(shown):
                    for y in range(x + 1, shown):
                        mask = ((1 << (hole[i] // 4)) | (1 << (hole[j] // 4))
                                | (1 << (board[x] // 4)) | (1 << (board[y] // 4)) | (1 << rank))
                        if _popcount(mask) == 5 and _is_straight(mask):
                            found = True
        if found:
            outs += 1
    return outs


@njit(cache=True)  # pragma: no cover - compiled native code
def _popcount(value: int) -> int:
    count = 0
    while value:
        value &= value - 1
        count += 1
    return count


@njit(cache=True)  # pragma: no cover - compiled native code
def postflop_bucket(hole: np.ndarray, board: np.ndarray, street: int, distribution: np.ndarray,
                    count: int, rank5: np.ndarray, comb: np.ndarray) -> int:
    shown = street + 2
    rank = best_rank(hole, board, shown, rank5, comb)
    strength = strength_bin(rank, distribution, count)
    if street == 3:
        return strength
    draw = flush_draw(hole, board, shown)
    outs = 0 if rank <= STRAIGHT_OR_BETTER else min(straight_out_ranks(hole, board, shown), 3)
    return (strength * 3 + draw) * 4 + outs
