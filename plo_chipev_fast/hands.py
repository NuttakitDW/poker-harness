"""Complete physical-hand lookup for the existing feature abstraction."""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import math
import time
from collections.abc import Sequence

import numpy as np

from plo_icm.abstraction import preflop_bucket
from plo_icm.cards import DECK, canonical_cards


def combinadic_index(cards: Sequence[int]) -> int:
    """Index a sorted four-card combination in itertools lexicographic order."""
    if len(cards) != 4 or tuple(cards) != tuple(sorted(cards)) or len(set(cards)) != 4:
        raise ValueError("cards must be four distinct sorted card IDs")
    if cards[0] < 0 or cards[-1] >= 52:
        raise ValueError("card IDs must be in [0, 52)")
    rank = 0
    previous = -1
    for position, card in enumerate(cards):
        for skipped in range(previous + 1, card):
            rank += math.comb(51 - skipped, 3 - position)
        previous = card
    return rank


@dataclasses.dataclass(frozen=True)
class HandLookup:
    combo_to_bucket: np.ndarray
    bucket_names: tuple[str, ...]
    build_seconds: float

    @property
    def physical_count(self) -> int:
        return int(self.combo_to_bucket.size)

    @property
    def bucket_count(self) -> int:
        return len(self.bucket_names)

    @classmethod
    def build(cls) -> HandLookup:
        started = time.perf_counter()
        observations = [preflop_bucket(tuple(DECK[index] for index in combo)) for combo in itertools.combinations(range(52), 4)]
        names = tuple(sorted(set(observations)))
        ids = {name: index for index, name in enumerate(names)}
        lookup = np.fromiter((ids[name] for name in observations), dtype=np.int16, count=len(observations))
        result = cls(lookup, names, time.perf_counter() - started)
        if result.physical_count != 270_725 or result.bucket_count != 572:
            raise RuntimeError("unexpected feature-abstraction cardinality")
        return result

    def bucket_for_cards(self, cards: Sequence[int]) -> int:
        return int(self.combo_to_bucket[combinadic_index(tuple(sorted(cards)))])

    def representation_hash(self) -> str:
        digest = hashlib.sha256(b"plo-chipev-fast-hand-lookup-v1")
        digest.update(self.combo_to_bucket.tobytes())
        for name in self.bucket_names:
            digest.update(name.encode())
            digest.update(b"\0")
        return digest.hexdigest()


def measure_exact_classes() -> dict[str, float | int]:
    """Measure exact canonical cardinality without allocating a dense policy."""
    started = time.perf_counter()
    classes = {
        canonical_cards(tuple(DECK[index] for index in combo), ())[0]
        for combo in itertools.combinations(range(52), 4)
    }
    count = len(classes)
    return {
        "physical_count": math.comb(52, 4),
        "exact_canonical_count": count,
        "seconds": time.perf_counter() - started,
        "dense_regret_strategy_bytes": 5_466 * count * 3 * 16,
    }

