"""The solver's range chart at a hero decision of a reviewed hand.

Every five-card hand that avoids the known board is weighted by how often the solver would have taken
the hero's earlier actions on this line with it (its buckets on each street), then counted with the
solver's mix at the decision. Summed per suit class and then per "first two cards" cell (the 13 x 13
matrix of the range explorer, where a hand sits in the cell of every pair it contains).
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

from .postflop import board_distribution, postflop_bucket

RANKS = "AKQJT98765432"


@njit(cache=True, boundscheck=True)  # pragma: no cover - compiled native code
def _colex5(a: int, b: int, c: int, d: int, e: int, comb: np.ndarray) -> int:
    return comb[a, 1] + comb[b, 2] + comb[c, 3] + comb[d, 4] + comb[e, 5]


@njit(parallel=True, boundscheck=True)  # pragma: no cover - compiled native code
def class_mix(board: np.ndarray, known: int, path_nodes: np.ndarray, path_slots: np.ndarray, path_streets: np.ndarray,
              node: int, node_street: int, count: int, policy: np.ndarray, row_start: np.ndarray,
              decision_index: np.ndarray, bucket_of: np.ndarray, class_of: np.ndarray, classes: int,
              rank5: np.ndarray, comb: np.ndarray) -> np.ndarray:
    """(classes, 1 + count): reach weight and weighted mix of each action, summed over the class's hands."""
    on = np.zeros(52, dtype=np.bool_)
    for k in range(known):
        on[board[k]] = True
    dists = np.zeros((4, 1326), dtype=np.int64)
    counts = np.zeros(4, dtype=np.int64)
    for street in range(1, 4):
        if street + 2 <= known:
            counts[street] = board_distribution(board, street + 2, rank5, comb, dists[street])
    out = np.zeros((52, classes, 1 + count))
    for a in prange(52):
        hole = np.empty(5, dtype=np.int64)
        buckets = np.empty(4, dtype=np.int64)
        if on[a]:
            continue
        for b in range(a + 1, 52):
            if on[b]:
                continue
            for c in range(b + 1, 52):
                if on[c]:
                    continue
                for d in range(c + 1, 52):
                    if on[d]:
                        continue
                    for e in range(d + 1, 52):
                        if on[e]:
                            continue
                        hole[0], hole[1], hole[2], hole[3], hole[4] = a, b, c, d, e
                        index = _colex5(a, b, c, d, e, comb)
                        buckets[0] = bucket_of[index]
                        for s in range(1, 4):
                            buckets[s] = -1
                        weight = 1.0
                        for i in range(path_nodes.size):
                            s = path_streets[i]
                            if buckets[s] < 0:
                                buckets[s] = postflop_bucket(hole, board, s, dists[s], counts[s], rank5, comb)
                            weight *= policy[row_start[decision_index[path_nodes[i]]] + buckets[s], path_slots[i]]
                            if weight <= 0.0:
                                break
                        if weight <= 0.0:
                            continue
                        if buckets[node_street] < 0:
                            buckets[node_street] = postflop_bucket(hole, board, node_street, dists[node_street],
                                                                   counts[node_street], rank5, comb)
                        row = row_start[decision_index[node]] + buckets[node_street]
                        cls = class_of[index]
                        out[a, cls, 0] += weight
                        for k in range(count):
                            out[a, cls, 1 + k] += weight * policy[row, k]
    return out.sum(axis=0)


def half_key(x: str, y: str) -> int:
    """Matrix cell of two cards, as plo-explorer.js halfKey: pairs on the diagonal, suited above it."""
    i, j = RANKS.index(x[0]), RANKS.index(y[0])
    if i == j:
        return i * 13 + i
    hi, lo = min(i, j), max(i, j)
    return hi * 13 + lo if x[1] == y[1] else lo * 13 + hi


def class_cells(cards_text: str) -> list[int]:
    cards = [cards_text[i:i + 2] for i in range(0, len(cards_text), 2)]
    return sorted({half_key(cards[i], cards[j]) for i in range(len(cards)) for j in range(i + 1, len(cards))})


def matrix(per_class: np.ndarray, class_texts: list[str]) -> list[list[float]]:
    """169 cells: [reach weight share, mix of each action] (mix normalised within the cell)."""
    count = per_class.shape[1] - 1
    cells = np.zeros((169, 1 + count))
    for cls, text in enumerate(class_texts):
        if per_class[cls, 0] <= 0:
            continue
        for key in class_cells(text):
            cells[key] += per_class[cls]
    total = cells[:, 0].max() if cells[:, 0].max() > 0 else 1.0
    out = []
    for key in range(169):
        w = cells[key, 0]
        mix = (cells[key, 1:] / w) if w > 0 else np.zeros(count)
        out.append([round(float(w / total), 3)] + [round(float(m), 3) for m in mix])
    return out
