"""Postflop hand features for Omaha 8-or-better, all computed natively from (hole, board).

High side: made-hand class relative to the board (top pair, set, nut straight, nut flush, top boat),
flush draw (nut / other / none) and straight outs. Low side: made-low rank against every low the board
allows (nut, second, third, worse, none), low-draw quality (nut, good, weak) and counterfeit
protection (three or more distinct low cards off the board). Board texture: low cards, pairing, suits.
Every feature depends only on ranks and on suit equality, so suit relabelling never changes a bucket.
"""

from __future__ import annotations

import numpy as np
from numba import njit

from .evaluator import BASE, FLUSH, FULL_HOUSE, HIGH_CARD, NO_LOW, PAIR, STRAIGHT, TRIPS, TWO_PAIR, high5, low5

HIGH_CLASSES = 12  # see high_class
FLUSH_DRAW_CLASSES = 3
STRAIGHT_DRAW_CLASSES = 3
LOW_CLASSES_EARLY = 18
LOW_CLASSES_RIVER = 6
TEXTURE_EARLY = 24
EARLY_KEYS = HIGH_CLASSES * FLUSH_DRAW_CLASSES * STRAIGHT_DRAW_CLASSES * LOW_CLASSES_EARLY * TEXTURE_EARLY
RIVER_KEYS = HIGH_CLASSES * 2 * 2 * LOW_CLASSES_RIVER


@njit(cache=True)
def omaha_high_n(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    best = -1
    for i in range(4):
        for j in range(i + 1, 4):
            for a in range(n):
                for b in range(a + 1, n):
                    for c in range(b + 1, n):
                        v = high5(hole[i], hole[j], board[a], board[b], board[c])
                        if v > best:
                            best = v
    return best


@njit(cache=True)
def omaha_low_n(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    best = NO_LOW
    for i in range(4):
        for j in range(i + 1, 4):
            for a in range(n):
                for b in range(a + 1, n):
                    for c in range(b + 1, n):
                        v = low5(hole[i], hole[j], board[a], board[b], board[c])
                        if v < best:
                            best = v
    return best


@njit(cache=True)
def _low_value(card: int) -> int:
    rank = card >> 2
    if rank == 12:
        return 1
    return rank + 2 if rank <= 6 else 0


@njit(cache=True)
def _low_mask(cards: np.ndarray, n: int) -> int:
    mask = 0
    for i in range(n):
        v = _low_value(cards[i])
        if v:
            mask |= 1 << v
    return mask


@njit(cache=True)
def _popcount(x: int) -> int:
    count = 0
    while x:
        x &= x - 1
        count += 1
    return count


@njit(cache=True)
def _window_mask(top: int) -> int:
    """Rank bitmask (bit = rank 0..12) of the straight ending at `top`; top 3 is the wheel."""
    if top == 3:
        return (1 << 12) | 0b1111
    return 0b11111 << (top - 4)


@njit(cache=True)
def _rank_mask(cards: np.ndarray, n: int) -> int:
    mask = 0
    for i in range(n):
        mask |= 1 << (cards[i] >> 2)
    return mask


@njit(cache=True)
def _straight_with(hole: np.ndarray, board_mask: int) -> int:
    """Highest straight top makeable with exactly two hole ranks and three board ranks, or -1."""
    for top in range(12, 2, -1):
        window = _window_mask(top)
        for i in range(4):
            for j in range(i + 1, 4):
                a, b = hole[i] >> 2, hole[j] >> 2
                if a == b or not (window >> a) & 1 or not (window >> b) & 1:
                    continue
                rest = window & ~(1 << a) & ~(1 << b)
                if rest & board_mask == rest:
                    return top
    return -1


@njit(cache=True)
def nut_straight_top(board: np.ndarray, n: int) -> int:
    board_mask = _rank_mask(board, n)
    for top in range(12, 2, -1):
        if _popcount(_window_mask(top) & board_mask) >= 3:
            return top
    return -1


@njit(cache=True)
def _flush_suit(board: np.ndarray, n: int) -> int:
    packed = 0
    for i in range(n):
        packed += 1 << 4 * (board[i] & 3)
    for s in range(4):
        if (packed >> 4 * s) & 15 >= 3:
            return s
    return -1


@njit(cache=True)
def _board_shape(board: np.ndarray, n: int) -> tuple[int, int]:
    """(1 if the board is paired, most cards of one suit)."""
    ranks = 0
    suits = 0
    paired = 0
    for i in range(n):
        bit = 1 << (board[i] >> 2)
        if ranks & bit:
            paired = 1
        ranks |= bit
        suits += 1 << 4 * (board[i] & 3)
    top = 0
    for s in range(4):
        c = (suits >> 4 * s) & 15
        if c > top:
            top = c
    return paired, top


@njit(cache=True)
def _holds_nut_flush_card(hole: np.ndarray, board: np.ndarray, n: int, suit: int) -> bool:
    """True when we hold the highest card of `suit` that is not on the board."""
    for rank in range(12, -1, -1):
        card = rank * 4 + suit
        on_board = False
        for i in range(n):
            if board[i] == card:
                on_board = True
        if on_board:
            continue
        for i in range(4):
            if hole[i] == card:
                return True
        return False
    return False


@njit(cache=True)
def high_class(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    """0 nothing (or only the board's pair or trips), 1 under pair, 2 top pair or overpair, 3 two pair, 4 trips, 5 top trips,
    6 straight, 7 nut straight, 8 flush, 9 nut flush, 10 full house, 11 top full house or better."""
    return high_class_of(omaha_high_n(hole, board, n), hole, board, n)


@njit(cache=True)
def high_class_of(v: int, hole: np.ndarray, board: np.ndarray, n: int) -> int:
    """high_class from an already computed omaha high value."""
    category = v // BASE ** 5
    first = (v // BASE ** 4) % BASE
    board_top = 0
    for i in range(n):
        r = board[i] >> 2
        if r > board_top:
            board_top = r
    if category == HIGH_CARD:
        return 0
    on_board = 0
    for i in range(n):
        if board[i] >> 2 == first:
            on_board += 1
    if category == PAIR:
        if on_board >= 2:
            return 0  # only the board pair: no hole card helps
        return 2 if first >= board_top else 1
    if category == TWO_PAIR:
        return 3
    if category == TRIPS:
        if on_board >= 3:
            return 0  # board trips
        return 5 if first == board_top else 4
    if category == STRAIGHT:
        return 7 if v % BASE ** 5 == nut_straight_top(board, n) else 6
    if category == FLUSH:
        return 9 if _holds_nut_flush_card(hole, board, n, _flush_suit(board, n)) else 8
    if category == FULL_HOUSE:
        return 11 if first == board_top else 10
    return 11


@njit(cache=True)
def flush_draw(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    """0 none, 1 flush draw, 2 nut flush draw (two hole cards of a suit with exactly two on board)."""
    best = 0
    for s in range(4):
        on_board = 0
        for i in range(n):
            if board[i] & 3 == s:
                on_board += 1
        in_hand = 0
        for i in range(4):
            if hole[i] & 3 == s:
                in_hand += 1
        if on_board == 2 and in_hand >= 2:
            level = 2 if _holds_nut_flush_card(hole, board, n, s) else 1
            if level > best:
                best = level
    return best


@njit(cache=True)
def straight_draw(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    """0 no draw (or straight made), 1 one or two out ranks, 2 three or more (a wrap)."""
    board_mask = _rank_mask(board, n)
    if _straight_with(hole, board_mask) >= 0:
        return 0
    outs = 0
    for r in range(13):
        if (board_mask >> r) & 1:
            continue
        if _straight_with(hole, board_mask | (1 << r)) >= 0:
            outs += 1
    if outs == 0:
        return 0
    return 1 if outs <= 2 else 2


@njit(cache=True)
def _best_low_code(a: int, b: int, board_mask: int) -> int:
    """Best low with hole low values a != b and the three lowest board low values not equal to a or b."""
    if a == b:
        return NO_LOW
    mask = (1 << a) | (1 << b)
    count = 2
    for v in range(1, 9):
        if count == 5:
            break
        if (board_mask >> v) & 1 and v != a and v != b:
            mask |= 1 << v
            count += 1
    if count < 5:
        return NO_LOW
    code = 0
    for v in range(8, 0, -1):
        if (mask >> v) & 1:
            code = code * 9 + v
    return code


@njit(cache=True)
def made_low_rank(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    """0 nut low, 1 second, 2 third, 3 worse, 4 no low. Ranked among distinct lows this board allows."""
    mine = omaha_low_n(hole, board, n)
    if mine == NO_LOW:
        return 4
    board_mask = _low_mask(board, n)
    better = 0
    s0 = s1 = s2 = -1
    for a in range(1, 9):
        for b in range(a + 1, 9):
            code = _best_low_code(a, b, board_mask)
            if code >= mine or code == s0 or code == s1 or code == s2:
                continue
            if better == 0:
                s0 = code
            elif better == 1:
                s1 = code
            else:
                s2 = code
            better += 1
            if better >= 3:
                return 3
    return better


@njit(cache=True)
def low_draw(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    """0 none, 1 nut draw, 2 good (second or third best two cards), 3 weak, from low cards off the board."""
    board_mask = _low_mask(board, n)
    mine = _low_mask(hole, 4) & ~board_mask
    if _popcount(mine) < 2:
        return 0
    lo0 = lo1 = 0
    found = 0
    for v in range(1, 9):
        if found < 2 and (mine >> v) & 1:
            if found == 0:
                lo0 = v
            else:
                lo1 = v
            found += 1
    # Order every two-card draw from values off the board by (higher card, lower card).
    index = 0
    for high in range(2, 9):
        if (board_mask >> high) & 1:
            continue
        for low in range(1, high):
            if (board_mask >> low) & 1:
                continue
            if high == lo1 and low == lo0:
                return 1 if index == 0 else 2 if index <= 2 else 3
            index += 1
    return 3


@njit(cache=True)
def protected(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    return 1 if _popcount(_low_mask(hole, 4) & ~_low_mask(board, n)) >= 3 else 0


@njit(cache=True)
def texture_early(board: np.ndarray, n: int) -> int:
    lows = _popcount(_low_mask(board, n))
    if lows > 3:
        lows = 3
    paired, top_suit = _board_shape(board, n)
    suitedness = 0 if top_suit <= 1 else 1 if top_suit == 2 else 2
    return (lows * 2 + paired) * 3 + suitedness


@njit(cache=True)
def early_key(hole: np.ndarray, board: np.ndarray, n: int) -> int:
    """Flop (n=3) and turn (n=4) raw bucket key in [0, EARLY_KEYS)."""
    if _popcount(_low_mask(board, n)) >= 3:
        low = made_low_rank(hole, board, n) * 2 + protected(hole, board, n)
    else:
        low = 10 + low_draw(hole, board, n) * 2 + protected(hole, board, n)
    key = high_class(hole, board, n)
    key = key * FLUSH_DRAW_CLASSES + flush_draw(hole, board, n)
    key = key * STRAIGHT_DRAW_CLASSES + straight_draw(hole, board, n)
    key = key * LOW_CLASSES_EARLY + low
    return key * TEXTURE_EARLY + texture_early(board, n)


@njit(cache=True)
def river_key(hole: np.ndarray, board: np.ndarray, high: int) -> int:
    """River raw bucket key in [0, RIVER_KEYS); `high` is the hand's omaha_high value on this board."""
    low = 0 if _popcount(_low_mask(board, 5)) < 3 else 1 + made_low_rank(hole, board, 5)
    paired, top_suit = _board_shape(board, 5)
    flushable = 1 if top_suit >= 3 else 0
    return ((high_class_of(high, hole, board, 5) * 2 + paired) * 2 + flushable) * LOW_CLASSES_RIVER + low
