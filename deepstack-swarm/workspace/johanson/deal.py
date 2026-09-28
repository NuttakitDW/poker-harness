"""Exact card-removal deal distributions over the 169 classes.

The Pricer's opponent model (`pushfold/pricer.py:20-28`) deals an opponent class g with
chance `PRIOR[g]`, independent of the hero's class h and of each other. Real dealing removes
the hero's two cards first, so an opponent's class is drawn from the remaining 50 cards.

This module builds the exact class-level deal distribution instead.

* `marginal()` -- `M[h, g] = P(opponent class g | hero class h)`, exactly `hands.M`.
* `joint2()`   -- `J[h, g, k] = P(two opponents hold classes g and k | hero class h)`, exact,
  counted by enumerating the 270,725 four-card sets a disjoint opponent pair occupies.

Why class-level is enough
-------------------------
Every quantity downstream (`eq3`, `pw`, `e2`, the strategy) is a function of the class. Within
one class, all combos give the *same* distribution over opponent classes: a suit permutation
maps one combo to another, preserves `class_of_cards`, and preserves the deck. So a
"best response over the 1326 combos, hero's combo fixed" is the same number as a class-level
best response, and this module's class joint is that number.

Validation
----------
`joint2()[h]` marginalised over either opponent must reproduce `M[h]`; the full tensor sums to
one per h. Both are checked in `check_deal.py`.

Written by the Johanson persona (swarm agent).
"""

from __future__ import annotations

import functools
import itertools
from pathlib import Path

import numpy as np

from pushfold import hands

N = len(hands.CLASSES)
COMBOS = hands.COMBOS
CLASS_OF = hands.CLASS_OF.astype(np.int64)
COUNTS = hands.COUNTS.astype(np.float64)
M = hands.M
PRIOR = hands.PRIOR
OPPONENT_COMBOS = hands.OPPONENT_COMBOS

CACHE = Path(__file__).resolve().parent / "deal-joint2.npz"


def _pair_class() -> np.ndarray:
    """PAIR[x, y]: class index of the two-card set {x, y}; -1 when x == y."""
    pc = np.full((52, 52), -1, dtype=np.int64)
    for x in range(52):
        for y in range(52):
            if x != y:
                pc[x, y] = hands.class_of_cards(x, y)
    return pc


def _cnt1() -> np.ndarray:
    """CNT1[k, x]: combos in class k that contain card x."""
    c = np.zeros((N, 52))
    rows = np.repeat(np.arange(len(COMBOS)), 2)
    np.add.at(c, (CLASS_OF[rows], COMBOS.reshape(-1)), 1.0)
    return c


@functools.lru_cache(maxsize=1)
def joint2(verbose: bool = False) -> np.ndarray:
    """J[h, g, k] = P(opp1 class g, opp2 class k | hero class h). Exact, rows sum to 1.

    For a four-card set S = a|b holding the two opponents' cards,
        #combos in class k disjoint from S = COUNTS[k] - sum_{x in S} CNT1[k, x]
                                             + #{pairs in S whose class is k},
    because a combo shares a card with S iff it contains one of S's 4 cards, and the
    two-card overlaps are the 6 pairs inside S. Then every ordered disjoint triple
    (a, b, c) is one four-set S, one of 6 ordered splits of S into (a, b), and one c.
    """
    if CACHE.exists():
        with np.load(CACHE) as saved:
            return saved["J"]
    cnt1 = _cnt1()
    pc = _pair_class()
    sets = np.array(list(itertools.combinations(range(52), 4)), dtype=np.int64)
    n_sets = len(sets)
    splits = [((0, 1), (2, 3)), ((2, 3), (0, 1)), ((0, 2), (1, 3)),
              ((1, 3), (0, 2)), ((0, 3), (1, 2)), ((1, 2), (0, 3))]
    T = np.zeros((N, N, N))
    chunk = 40000
    import time
    began = time.perf_counter()
    for lo in range(0, n_sets, chunk):
        S = sets[lo:lo + chunk]
        size = len(S)
        colsum = np.zeros((size, N))
        for j in range(4):
            colsum += cnt1[:, S[:, j]].T
        paircount = np.zeros(size * N)
        rows = np.tile(np.arange(size), 6)   # cols is grouped by pair, not by set
        cols = np.concatenate([pc[S[:, i], S[:, j]] for i, j in
                               ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))])
        np.add.at(paircount, rows * N + cols, 1.0)
        nd = COUNTS[None, :] - colsum + paircount.reshape(size, N)   # (size, N)
        for (i, j), (k, l) in splits:
            np.add.at(T, (pc[S[:, i], S[:, j]], pc[S[:, k], S[:, l]]), nd)
        if verbose and (lo // chunk) % 3 == 0:
            print(f"  {lo + size:,}/{n_sets:,} four-sets  {time.perf_counter() - began:,.0f}s")
    J = T / T.sum(axis=(1, 2), keepdims=True)
    np.savez_compressed(CACHE, J=J.astype(np.float64))
    return J


@functools.lru_cache(maxsize=1)
def _pc() -> np.ndarray:
    return _pair_class()


@functools.lru_cache(maxsize=1)
def _class_combos() -> tuple[np.ndarray, np.ndarray]:
    padded = np.zeros((N, 12, 2), dtype=np.int64)
    for cls in range(N):
        mine = COMBOS[CLASS_OF == cls]
        padded[cls, :len(mine)] = mine
    return padded, COUNTS.astype(np.int64)


def _draw(masks: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """One card uniform from the free cards for each row, as (cards, updated masks)."""
    card = rng.integers(0, 52, size=len(masks)).astype(np.int64)
    blocked = (masks >> card & 1) == 1
    while blocked.any():                         # redraw the blocked rows only
        card[blocked] = rng.integers(0, 52, size=int(blocked.sum())).astype(np.int64)
        blocked = (masks >> card & 1) == 1
    return card, masks | (np.int64(1) << card)


def opponent_sets(hero_class: np.ndarray, n: int, samples: int,
                  rng: np.random.Generator) -> np.ndarray:
    """(samples, n-1) opponent class indices under exact sequential dealing.

    Hero's two cards are drawn uniformly from `hero_class` (one row of classes per sample --
    pass a length-`samples` vector). Every other seat is then dealt uniformly from the cards
    still unseen, so the opponents are blocked by the hero and by each other. This is the
    real deal; the Pricer's independent prior is not.
    """
    m = n - 1
    pc = _pc()
    padded, counts = _class_combos()
    masks = np.zeros(samples, dtype=np.int64)
    hero_class = np.asarray(hero_class, dtype=np.int64)
    picks = (rng.random(samples) * counts[hero_class]).astype(np.int64)
    combo = padded[hero_class, picks]
    for c in (combo[:, 0], combo[:, 1]):
        masks |= np.int64(1) << c.astype(np.int64)
    out = np.zeros((samples, m), dtype=np.int64)
    for j in range(m):
        a, masks = _draw(masks, rng)
        b, masks = _draw(masks, rng)
        out[:, j] = pc[a, b]
    return out
