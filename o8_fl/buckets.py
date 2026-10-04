"""Card abstraction: exact preflop classes and dense postflop bucket ids.

Preflop has no abstraction: each four-card hand maps to one of 16,432 suit-isomorphic classes.
After the flop a hand maps to its feature key (features.py). Flop and turn keys are made dense by
sampling deals once; a key never seen in sampling falls into bucket 0, which is reserved for that.
River keys are already small and are used as they are.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import time
from pathlib import Path

import numpy as np
from numba import njit

from .cards import RANKS
from .features import EARLY_KEYS, RIVER_KEYS, early_key

PREFLOP_CLASSES = 16_432
HANDS = math.comb(52, 4)
UNSEEN = 0


def combo_index(cards: tuple[int, ...]) -> int:
    """Lexicographic rank of a sorted four-card combination, matching itertools.combinations(range(52), 4)."""
    rank, previous = 0, -1
    for position, card in enumerate(cards):
        for skipped in range(previous + 1, card):
            rank += math.comb(51 - skipped, 3 - position)
        previous = card
    return rank


def canonical(cards: tuple[int, ...]) -> tuple[int, ...]:
    return min(tuple(sorted((c >> 2) * 4 + perm[c & 3] for c in cards))
               for perm in itertools.permutations(range(4)))


def class_name(cards: tuple[int, ...]) -> str:
    """Readable name of a canonical class: ranks high to low with suits renamed s, h, d, c in first-seen order."""
    ordered = sorted(cards, key=lambda c: (-(c >> 2), c & 3))
    names, rename = [], {}
    for c in ordered:
        rename.setdefault(c & 3, "shdc"[len(rename)])
        names.append(RANKS[c >> 2] + rename[c & 3])
    return "".join(names)


def build_preflop() -> tuple[np.ndarray, tuple[str, ...], np.ndarray]:
    ids: dict[tuple[int, ...], int] = {}
    lookup = np.empty(HANDS, dtype=np.int32)
    for index, combo in enumerate(itertools.combinations(range(52), 4)):
        lookup[index] = ids.setdefault(canonical(combo), len(ids))
    if len(ids) != PREFLOP_CLASSES:
        raise RuntimeError(f"expected {PREFLOP_CLASSES} preflop classes, got {len(ids)}")
    names = tuple(class_name(c) for c in ids)
    weights = np.bincount(lookup, minlength=PREFLOP_CLASSES).astype(np.int32)
    return lookup, names, weights


@njit(cache=True)
def _sample_early_keys(samples: int, seed: int, n: int) -> np.ndarray:
    np.random.seed(seed)
    seen = np.zeros(EARLY_KEYS, dtype=np.int64)
    deck = np.arange(52)
    for _ in range(samples):
        np.random.shuffle(deck)
        seen[early_key(deck[:4], deck[4:9], n)] += 1
    return seen


def dense_map(counts: np.ndarray) -> np.ndarray:
    mapping = np.full(counts.size, UNSEEN, dtype=np.int32)
    seen = np.flatnonzero(counts)
    mapping[seen] = np.arange(1, seen.size + 1, dtype=np.int32)
    return mapping


@dataclasses.dataclass(frozen=True)
class Abstraction:
    preflop: np.ndarray  # combo index -> class
    preflop_names: tuple[str, ...]
    preflop_weights: np.ndarray  # physical hands per class
    flop_map: np.ndarray  # raw early key -> dense id
    turn_map: np.ndarray

    @property
    def bucket_counts(self) -> tuple[int, int, int, int]:
        return (PREFLOP_CLASSES, int(self.flop_map.max()) + 1, int(self.turn_map.max()) + 1, RIVER_KEYS)

    @classmethod
    def build(cls, samples: int = 4_000_000, seed: int = 1) -> Abstraction:
        started = time.perf_counter()
        preflop, names, weights = build_preflop()
        flop = dense_map(_sample_early_keys(samples, seed, 3))
        turn = dense_map(_sample_early_keys(samples, seed + 1, 4))
        result = cls(preflop, names, weights, flop, turn)
        print(f"abstraction built in {time.perf_counter() - started:.0f}s: buckets {result.bucket_counts}")
        return result

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, preflop=self.preflop, names=np.array(self.preflop_names),
                            weights=self.preflop_weights, flop=self.flop_map, turn=self.turn_map)

    @classmethod
    def load(cls, path: Path) -> Abstraction:
        data = np.load(path)
        return cls(data["preflop"], tuple(str(n) for n in data["names"]), data["weights"], data["flop"],
                   data["turn"])

    @classmethod
    def cached(cls, path: Path) -> Abstraction:
        if path.exists():
            return cls.load(path)
        result = cls.build()
        result.save(path)
        return result

    def preflop_class(self, cards: tuple[int, ...]) -> int:
        return int(self.preflop[combo_index(tuple(sorted(cards)))])


