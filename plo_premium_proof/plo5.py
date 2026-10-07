"""PLO5 (five hole cards) preflop buckets for the all-streets solver.

The solver kernels take the number of hole cards from the length of ``bucket_of`` (PLO4: 270,725
four-card hands, PLO5: 2,598,960 five-card hands, both indexed by colex rank), so PLO5 only needs
its own preflop table. Postflop buckets (plo_premium_proof.postflop) already work for any hand size.

Every suit-isomorphism class of five-card hands (134,459) gets two Monte Carlo equities with the
hand's own cards removed: heads-up against one random hand and three-way against two. Buckets cut the
heads-up equity into equal-weight bands and each band by the three-way equity, so hands that are
strong heads-up but weak multiway (and the other way round) stay apart.

    .venv/bin/python -m plo_premium_proof.plo5 build          (tmp/plo5/tables.npz, ~10 minutes)
"""

from __future__ import annotations

import argparse
import itertools
import math
import time
from pathlib import Path

import numpy as np
from numba import njit, prange

from plo_equity.cards import card_text

from .kernels import plo_rank
from .tables import comb_table, five_card_ranks

PATH = Path("tmp/plo5/tables.npz")
HANDS5 = math.comb(52, 5)
BANDS, SPLITS = 40, 25  # 1,000 preflop buckets
SAMPLES = 3000


def _canonical(cards: tuple[int, ...], perms) -> tuple[int, ...]:
    return min(tuple(sorted(4 * (c // 4) + p[c % 4] for c in cards)) for p in perms)


def hand_classes() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(class of every hand by colex rank, class representative cards, combos per class)."""
    comb = comb_table()
    perms = list(itertools.permutations(range(4)))
    keys: dict[tuple[int, ...], int] = {}
    class_of = np.empty(HANDS5, dtype=np.int32)
    for cards in itertools.combinations(range(52), 5):
        key = _canonical(cards, perms)
        cls = keys.setdefault(key, len(keys))
        class_of[sum(int(comb[c, i + 1]) for i, c in enumerate(cards))] = cls
    reps = np.zeros((len(keys), 5), dtype=np.int64)
    for key, cls in keys.items():
        reps[cls] = key
    combos = np.bincount(class_of, minlength=len(keys))
    # number classes by canonical cards, so the order is stable and readable
    order = np.lexsort(reps.T[::-1])
    renumber = np.empty(len(keys), dtype=np.int32)
    renumber[order] = np.arange(len(keys))
    return renumber[class_of], reps[order], combos[order]


@njit(cache=True)  # pragma: no cover - compiled native code
def _draw(deck: np.ndarray, size: int, count: int, out: np.ndarray, start: int) -> None:
    for k in range(count):
        j = start + k + np.random.randint(size - start - k)
        deck[start + k], deck[j] = deck[j], deck[start + k]
        out[k] = deck[start + k]


@njit(cache=True, parallel=True)  # pragma: no cover - compiled native code
def equities(reps: np.ndarray, samples: int, rank5: np.ndarray, comb: np.ndarray, seed: int) -> np.ndarray:
    """(classes, 2): equity heads-up against one random hand and three-way against two."""
    n = reps.shape[0]
    out = np.zeros((n, 2))
    for c in prange(n):
        np.random.seed(seed + c)
        hero = reps[c]
        deck = np.empty(47, dtype=np.int64)
        k = 0
        for card in range(52):
            if card != hero[0] and card != hero[1] and card != hero[2] and card != hero[3] and card != hero[4]:
                deck[k] = card
                k += 1
        opp1 = np.empty(5, dtype=np.int64)
        opp2 = np.empty(5, dtype=np.int64)
        board = np.empty(5, dtype=np.int64)
        hu = 0.0
        three = 0.0
        for _ in range(samples):
            _draw(deck, 47, 5, opp1, 0)
            _draw(deck, 47, 5, board, 5)
            _draw(deck, 47, 5, opp2, 10)
            h = plo_rank(hero, board, rank5, comb)
            a = plo_rank(opp1, board, rank5, comb)
            b = plo_rank(opp2, board, rank5, comb)
            hu += 1.0 if h < a else 0.5 if h == a else 0.0
            best = min(a, b)
            if h < best:
                three += 1.0
            elif h == best:
                ties = 1 + (1 if a == h else 0) + (1 if b == h else 0)
                three += 1.0 / ties
        out[c, 0] = hu / samples
        out[c, 1] = three / samples
    return out


def weighted_cuts(values: np.ndarray, weights: np.ndarray, parts: int) -> np.ndarray:
    """Inner cut points that split ``values`` into ``parts`` bands of equal total weight."""
    order = np.argsort(values, kind="stable")
    cum = np.cumsum(weights[order]) / weights.sum()
    picks = np.searchsorted(cum, np.arange(1, parts) / parts)
    return values[order][np.minimum(picks, len(values) - 1)]


def class_buckets(eq: np.ndarray, combos: np.ndarray) -> np.ndarray:
    weights = combos.astype(np.float64)
    band = np.searchsorted(weighted_cuts(eq[:, 0], weights, BANDS), eq[:, 0], side="right")
    bucket = np.empty(len(eq), dtype=np.int16)
    for b in range(BANDS):
        mine = np.flatnonzero(band == b)
        cuts = weighted_cuts(eq[mine, 1], weights[mine], SPLITS)
        bucket[mine] = b * SPLITS + np.searchsorted(cuts, eq[mine, 1], side="right")
    return bucket


def build(path: Path = PATH, samples: int = SAMPLES) -> dict:
    started = time.perf_counter()
    class_of, reps, combos = hand_classes()
    print(f"{len(reps):,} classes in {time.perf_counter() - started:.0f}s", flush=True)
    started = time.perf_counter()
    eq = equities(reps, samples, five_card_ranks(), comb_table(), 1)
    print(f"equities in {time.perf_counter() - started:.0f}s", flush=True)
    bucket = class_buckets(eq, combos)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, class_of=class_of, reps=reps, combos=combos, equity=eq, class_bucket=bucket,
             bucket_of=bucket[class_of], samples=samples)
    return {"classes": len(reps), "buckets": int(bucket.max()) + 1}


class Plo5Tables:
    """Stands in for tables.HandTables in the solver: ``bucket_of`` by colex rank, ``bucket_count``."""

    def __init__(self, path: Path = PATH):
        data = np.load(path)
        self.bucket_of = data["bucket_of"].astype(np.int32)
        self.class_of = data["class_of"]
        self.reps = data["reps"]
        self.combos = data["combos"]
        self.equity = data["equity"]
        self.class_bucket = data["class_bucket"]

    @property
    def bucket_count(self) -> int:
        return int(self.class_bucket.max()) + 1

    def describe(self, cls: int) -> str:
        return card_text(tuple(int(c) for c in self.reps[cls]))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build",))
    parser.add_argument("--samples", type=int, default=SAMPLES)
    args = parser.parse_args(argv)
    print(build(samples=args.samples))


if __name__ == "__main__":
    main()
