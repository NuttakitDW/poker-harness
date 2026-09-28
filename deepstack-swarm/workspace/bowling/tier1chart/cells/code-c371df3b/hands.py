"""The 169 starting-hand classes, the 1,326 combos behind them and the blocker matrix W.

Cards are 0-51 as rank * 4 + suit, rank 0 = deuce, 12 = ace (same as scripts/voice/equity_eval.py).
Classes sit on the usual 13x13 grid: row and column run A..2, suited above the diagonal,
offsuit below, so class index = row * 13 + col.
"""

from __future__ import annotations

import itertools

import numpy as np

RANKS = "23456789TJQKA"
SIZE = 13
DECK = 52
OPPONENT_COMBOS = 1225  # C(50, 2): combos left for one opponent once you hold two cards


def _label(row: int, col: int) -> str:
    high, low = RANKS[12 - min(row, col)], RANKS[12 - max(row, col)]
    if row == col:
        return high + low
    return high + low + ("s" if row < col else "o")


CLASSES: tuple[str, ...] = tuple(_label(r, c) for r in range(SIZE) for c in range(SIZE))
_INDEX = {label: i for i, label in enumerate(CLASSES)}


def index(label: str) -> int:
    """Class index of a label such as AA, AKs, 72o."""
    try:
        return _INDEX[label]
    except KeyError:
        raise ValueError(f"unknown hand class {label!r}; use AA, AKs, AKo style") from None


def class_of_cards(a: int, b: int) -> int:
    high, low = max(a // 4, b // 4), min(a // 4, b // 4)
    row, col = 12 - high, 12 - low
    if high == low or a % 4 != b % 4:
        return col * SIZE + row  # pair (row == col) or offsuit: below the diagonal
    return row * SIZE + col


COMBOS = np.array(list(itertools.combinations(range(DECK), 2)), dtype=np.int16)
CLASS_OF = np.array([class_of_cards(int(a), int(b)) for a, b in COMBOS], dtype=np.int16)
COUNTS = np.bincount(CLASS_OF, minlength=len(CLASSES)).astype(np.int64)
PRIOR = COUNTS / COUNTS.sum()  # chance of being dealt each class


def _blockers() -> np.ndarray:
    """W[i, j] = ordered combo pairs (one from class i, one from class j) that share no card."""
    masks = (np.int64(1) << COMBOS[:, 0].astype(np.int64)) | (np.int64(1) << COMBOS[:, 1].astype(np.int64))
    disjoint = (masks[:, None] & masks[None, :]) == 0
    onehot = np.zeros((len(COMBOS), len(CLASSES)), dtype=np.int64)
    onehot[np.arange(len(COMBOS)), CLASS_OF] = 1
    return onehot.T @ disjoint.astype(np.int64) @ onehot


W = _blockers()
# M[h, g] = P(an opponent holds class g | I hold class h). Rows sum to 1.
M = W / (COUNTS[:, None] * OPPONENT_COMBOS)
