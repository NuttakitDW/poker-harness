"""Strength buckets for O8 postflop: quick to compute from the cards, so the page can show every turn
and work out river buckets in the browser (the equity buckets of pool.py take ~9 s per board).

A bucket joins the PLO4 high-hand bucket of plo_premium_proof.postflop (high strength against all
two-card holdings x flush draw x straight outs on flop and turn, strength alone on the river) with
a low grade:

    0  no low and no low draw
    1  weak low (made, more than 35% of the holdings that make a low make a better one) or a weak
       draw (second card 6-8)
    2  made low with at most 35% better, or a draw with the second card 4-5
    3  made low with at most 10% better, or a draw to A2, A3 or 23
    4  nut low (no holding makes a better one)

Flop and turn: high bucket (120) x 5 = 600 buckets. River: high strength (10) x 5 = 50.

    .venv/bin/python -m o8_fl.strength pool --source tmp/o8_fl/pool_v2.npz --out tmp/o8_fl/pool_v3.npz
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from numba import njit, prange

from plo_premium_proof.postflop import board_distribution, postflop_bucket
from plo_premium_proof.tables import comb_table, five_card_ranks

from .pool import DealPool

LOW_GRADES = 5
COUNTS = (120 * LOW_GRADES, 120 * LOW_GRADES, 10 * LOW_GRADES)  # flop, turn, river
NO_LOW = 1 << 30
NO_BUCKET = 65535


@njit(cache=True)  # pragma: no cover - compiled native code
def low_value(card: int) -> int:
    """A..8 as 1..8 for the low, 0 for cards above 8."""
    rank = card // 4
    if rank == 12:
        return 1
    return rank + 2 if rank <= 6 else 0


@njit(cache=True)  # pragma: no cover - compiled native code
def low5(a: int, b: int, x: int, y: int, z: int) -> int:
    """Eight-or-better low of five cards, smaller is better; NO_LOW when they do not make one."""
    v = np.array([low_value(a), low_value(b), low_value(x), low_value(y), low_value(z)])
    for i in range(5):
        if v[i] == 0:
            return NO_LOW
        for j in range(i):
            if v[i] == v[j]:
                return NO_LOW
    v.sort()
    return (((v[4] * 9 + v[3]) * 9 + v[2]) * 9 + v[1]) * 9 + v[0]


@njit(cache=True)  # pragma: no cover - compiled native code
def best_low_pair(a: int, b: int, board: np.ndarray, shown: int) -> int:
    best = NO_LOW
    for x in range(shown):
        for y in range(x + 1, shown):
            for z in range(y + 1, shown):
                value = low5(a, b, board[x], board[y], board[z])
                if value < best:
                    best = value
    return best


@njit(cache=True)  # pragma: no cover - compiled native code
def best_low(hole: np.ndarray, board: np.ndarray, shown: int) -> int:
    best = NO_LOW
    for i in range(4):
        for j in range(i + 1, 4):
            value = best_low_pair(hole[i], hole[j], board, shown)
            if value < best:
                best = value
    return best


@njit(cache=True)  # pragma: no cover - compiled native code
def low_distribution(board: np.ndarray, shown: int, out: np.ndarray) -> int:
    """Sorted best low of every two-card holding off the board (NO_LOW included); returns the count."""
    count = 0
    for a in range(52):
        if _on(a, board, shown):
            continue
        for b in range(a + 1, 52):
            if _on(b, board, shown):
                continue
            out[count] = best_low_pair(a, b, board, shown)
            count += 1
    out[:count].sort()
    return count


@njit(cache=True)  # pragma: no cover - compiled native code
def _on(card: int, board: np.ndarray, shown: int) -> bool:
    for k in range(shown):
        if board[k] == card:
            return True
    return False


@njit(cache=True)  # pragma: no cover - compiled native code
def low_grade(hole: np.ndarray, board: np.ndarray, shown: int, distribution: np.ndarray, count: int) -> int:
    made = best_low(hole, board, shown)
    if made < NO_LOW:
        better = np.searchsorted(distribution[:count], made)  # strictly better lows sort first
        if better == 0:
            return 4
        share = better / np.searchsorted(distribution[:count], NO_LOW)  # among holdings that make a low
        return 3 if share <= 0.1 else 2 if share <= 0.35 else 1
    if shown == 5:
        return 0
    seen = np.zeros(9, dtype=np.bool_)
    board_lows = 0
    for k in range(shown):
        v = low_value(board[k])
        if v and not seen[v]:
            seen[v] = True
            board_lows += 1
    if 3 - board_lows > 5 - shown:
        return 0  # the board cannot bring three low cards in time
    first = second = 9
    for card in hole:
        v = low_value(card)
        if v == 0 or seen[v] or v == first or v == second:
            continue
        if v < first:
            first, second = v, first
        elif v < second:
            second = v
    if second == 9:
        return 0
    return 3 if second <= 3 else 2 if second <= 5 else 1


@njit(cache=True)  # pragma: no cover - compiled native code
def bucket(hole: np.ndarray, board: np.ndarray, street: int, hi_dist: np.ndarray, hi_count: int,
           lo_dist: np.ndarray, lo_count: int, rank5: np.ndarray, comb: np.ndarray) -> int:
    """Street 1-3 bucket of ``hole``; ``board`` holds at least street + 2 cards."""
    high = postflop_bucket(hole, board, street, hi_dist, hi_count, rank5, comb)
    return high * LOW_GRADES + low_grade(hole, board, street + 2, lo_dist, lo_count)


@njit(cache=True, parallel=True)  # pragma: no cover - compiled native code
def deal_buckets(cards: np.ndarray, rank5: np.ndarray, comb: np.ndarray) -> np.ndarray:
    """(n, 2, 3) buckets for pool deals laid out as hole0, hole1, board (13 cards)."""
    n = cards.shape[0]
    out = np.empty((n, 2, 3), dtype=np.uint16)
    for d in prange(n):
        board = cards[d, 8:13].astype(np.int64)
        hi_dist = np.empty(1326, dtype=np.int64)
        lo_dist = np.empty(1326, dtype=np.int64)
        for street in range(1, 4):
            shown = street + 2
            hi_count = board_distribution(board, shown, rank5, comb, hi_dist)
            lo_count = low_distribution(board, shown, lo_dist)
            for p in range(2):
                hole = cards[d, 4 * p:4 * p + 4].astype(np.int64)
                out[d, p, street - 1] = bucket(hole, board, street, hi_dist, hi_count, lo_dist, lo_count, rank5, comb)
    return out


@njit(cache=True, parallel=True)  # pragma: no cover - compiled native code
def board_buckets(hands: np.ndarray, board: np.ndarray, street: int, rank5: np.ndarray, comb: np.ndarray) -> np.ndarray:
    """Bucket of every hand (rows of card ids) on ``board`` (street + 2 cards); NO_BUCKET on a clash."""
    shown = street + 2
    hi_dist = np.empty(1326, dtype=np.int64)
    lo_dist = np.empty(1326, dtype=np.int64)
    hi_count = board_distribution(board, shown, rank5, comb, hi_dist)
    lo_count = low_distribution(board, shown, lo_dist)
    out = np.empty(hands.shape[0], dtype=np.uint16)
    for i in prange(hands.shape[0]):
        hole = hands[i]
        clash = False
        for card in hole:
            if _on(card, board, shown):
                clash = True
        out[i] = NO_BUCKET if clash else bucket(hole, board, street, hi_dist, hi_count, lo_dist, lo_count, rank5, comb)
    return out


def build_pool(source: Path, out: Path, block: int = 1_000_000) -> DealPool:
    """The source pool's deals with strength buckets in place of its equity buckets."""
    cards = DealPool.load(source).cards
    rank5, comb = five_card_ranks(), comb_table()
    buckets = np.empty((len(cards), 2, 3), dtype=np.uint16)
    for start in range(0, len(cards), block):
        started = time.perf_counter()
        buckets[start:start + block] = deal_buckets(cards[start:start + block], rank5, comb)
        print(f"{start + block:,} deals: {time.perf_counter() - started:.0f}s", flush=True)
    # DealPool reads each street's bucket count from its centroid rows; strength buckets need none.
    pool = DealPool(cards, buckets, tuple(np.zeros((k, 1), dtype=np.float32) for k in COUNTS))
    pool.save(out)
    return pool


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    pool = sub.add_parser("pool")
    pool.add_argument("--source", type=Path, default=Path("tmp/o8_fl/pool_v2.npz"))
    pool.add_argument("--out", type=Path, default=Path("tmp/o8_fl/pool_v3.npz"))
    args = parser.parse_args(argv)
    build_pool(args.source, args.out)


if __name__ == "__main__":
    main()
