"""Flop library for the postflop page: which flops to show, and every hand's flop bucket on each.

Buckets come from the same equity features and k-means centroids as training, so a hand's flop
strategy is the strategy of its bucket. Per flop the page gets one uint16 bucket per physical
four-card hand in class order (all combos of class 0, then class 1, ...), NO_BUCKET where the hand
uses a board card, which lets it average each preflop class over the combos the board leaves.
"""

from __future__ import annotations

import itertools
from collections import defaultdict

import numpy as np
from numba import njit, prange

from .buckets import Abstraction
from .cards import RANKS, card_text
from .equity import FEATURES, hand_features
from .pool import SAMPLES, assign
from .ranges import COMBOS

NO_BUCKET = 65535
ALL_FLOPS = 1755  # suit-isomorphic flops
LOW_RANKS = set("A2345678")


def _canonical(cards: tuple[int, ...]) -> tuple[int, ...]:
    return min(tuple(sorted((c >> 2) * 4 + perm[c & 3] for c in cards)) for perm in itertools.permutations(range(4)))


def canonical_flops() -> list[tuple[tuple[int, ...], int]]:
    """Every suit-isomorphic flop with the number of physical flops it stands for."""
    counts: dict[tuple[int, ...], int] = defaultdict(int)
    for flop in itertools.combinations(range(52), 3):
        counts[_canonical(flop)] += 1
    return sorted(counts.items())


def texture(flop: tuple[int, ...]) -> tuple[str, str, int, str]:
    """(suits, pairing, distinct low ranks, top card band)."""
    suits = len({c & 3 for c in flop})
    ranks = [RANKS[c >> 2] for c in flop]
    distinct = len(set(ranks))
    top = max(c >> 2 for c in flop)
    band = "A" if top == 12 else "K-Q" if top >= 10 else "J-9" if top >= 7 else "8-2"
    return ({3: "rainbow", 2: "two-tone", 1: "monotone"}[suits], {3: "unpaired", 2: "paired", 1: "trips"}[distinct],
            len(set(ranks) & LOW_RANKS), band)


def select_flops(count: int, seed: int = 0) -> list[tuple[int, ...]]:
    """`count` distinct canonical flops: one per texture first, the rest in proportion to how often each
    texture is dealt, drawn at random within the texture."""
    rng = np.random.default_rng(seed)
    groups: dict[tuple, list[tuple[tuple[int, ...], int]]] = defaultdict(list)
    for flop, weight in canonical_flops():
        groups[texture(flop)].append((flop, weight))
    if count < len(groups):
        raise ValueError(f"need at least {len(groups)} flops to cover every texture")
    picked: list[tuple[int, ...]] = []
    remaining = {key: list(flops) for key, flops in sorted(groups.items())}

    def draw(key: tuple) -> None:
        flops = remaining[key]
        weights = np.array([w for _, w in flops], dtype=float)
        i = int(rng.choice(len(flops), p=weights / weights.sum()))
        picked.append(flops.pop(i)[0])

    for key in remaining:
        draw(key)
    total = {key: sum(w for _, w in flops) for key, flops in groups.items()}
    while len(picked) < count:
        # Give the next flop to the texture furthest below its share of all dealt flops.
        key = max((k for k in remaining if remaining[k]),
                  key=lambda k: total[k] / 22100 - sum(texture(f) == k for f in picked) / max(len(picked), 1))
        draw(key)
    return sorted(picked)


def class_order(abstraction: Abstraction) -> np.ndarray:
    """Combo indices sorted by preflop class (stable), the order of a flop file."""
    return np.argsort(abstraction.preflop, kind="stable")


@njit(cache=True, parallel=True)
def _features(flop: np.ndarray, order: np.ndarray, combos: np.ndarray, seed: int, runouts: int, opponents: int,
              strong: int, cdf: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = order.shape[0]
    points = np.zeros((n, FEATURES), dtype=np.float32)
    clash = np.zeros(n, dtype=np.bool_)
    board = np.zeros(5, dtype=np.int64)
    board[:3] = flop
    for i in prange(n):
        hole = combos[order[i]].copy()
        for c in hole:
            if c == flop[0] or c == flop[1] or c == flop[2]:
                clash[i] = True
        if clash[i]:
            continue
        points[i] = hand_features(hole, board, 3, runouts, opponents, strong, combos, cdf, seed + i)
    return points, clash


def flop_buckets(flop: np.ndarray, centroids: np.ndarray, order: np.ndarray, cdf: np.ndarray, seed: int = 0,
                 runouts: int = SAMPLES[0][0], opponents: int = SAMPLES[0][1],
                 strong: int = SAMPLES[0][2]) -> np.ndarray:
    """Flop bucket of every hand in `order`; `cdf` is the strong range (ranges.load_cdf)."""
    points, clash = _features(np.asarray(flop, dtype=np.int64), order, COMBOS, seed, runouts, opponents, strong,
                              cdf)
    # Older 3-number centroids use only the random-hand part of the score.
    points = np.ascontiguousarray(points[:, :centroids.shape[1]])
    buckets = assign(points, np.ascontiguousarray(centroids, dtype=np.float32)).astype(np.uint16)
    buckets[clash] = NO_BUCKET
    return buckets


def representatives(abstraction: Abstraction, flop: tuple[int, ...]) -> dict[int, str]:
    """For classes whose listed cards use a board card: another combo of the class that does not."""
    board = set(flop)
    out = {}
    for cls, name in enumerate(abstraction.preflop_names):
        cards = {RANKS.index(name[i]) * 4 + "cdhs".index(name[i + 1]) for i in range(0, 8, 2)}
        if not cards & board:
            continue
        for index in np.flatnonzero(abstraction.preflop == cls):
            combo = COMBOS[index]
            if not set(combo.tolist()) & board:
                out[cls] = "".join(card_text(int(c)) for c in sorted(combo, key=lambda c: (-(c >> 2), c & 3)))
                break
    return out


def flop_label(flop: tuple[int, ...]) -> str:
    return "".join(card_text(c) for c in sorted(flop, key=lambda c: (-(c >> 2), c & 3)))
