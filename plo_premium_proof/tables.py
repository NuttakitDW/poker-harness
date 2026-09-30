"""Colex-indexed lookup tables shared by the numba kernels, cached on disk."""

from __future__ import annotations

import dataclasses
import itertools
import math
import random
from pathlib import Path

import numpy as np
from phevaluator import _pheval

from plo_chipev_fast.hands import HandLookup
from plo_chipev_fast.tree import ACTION_IDS, PublicTree
from plo_equity.cards import canonical_hand, card_text
from plo_thesis_audit.tiers import TIERS, TierLookup

CACHE_DIR = Path(__file__).resolve().parents[1] / "tmp" / "plo_premium_proof" / "cache"
HANDS4 = math.comb(52, 4)
HANDS5 = math.comb(52, 5)
PREMIUM = TIERS.index("Premium")
FIRST_IN_POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB")


def comb_table() -> np.ndarray:
    """``comb[n, k]`` for colex indexing of up to five cards."""
    table = np.zeros((53, 6), dtype=np.int64)
    for n in range(53):
        for k in range(6):
            table[n, k] = math.comb(n, k)
    return table


def colex_index(cards: tuple[int, ...]) -> int:
    return sum(math.comb(card, offset) for offset, card in enumerate(sorted(cards), 1))


def five_card_ranks(cache_dir: Path = CACHE_DIR) -> np.ndarray:
    """phevaluator rank (lower is stronger) for every 5-card set, colex order."""
    path = cache_dir / "rank5_colex.npy"
    if path.exists():
        ranks = np.load(path)
        if ranks.shape == (HANDS5,):
            return ranks
    ranks = np.empty(HANDS5, dtype=np.int16)
    evaluate = _pheval.evaluate_5cards
    for cards in itertools.combinations(range(52), 5):
        ranks[colex_index(cards)] = evaluate(*cards)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(path, ranks)
    return ranks


@dataclasses.dataclass(frozen=True)
class HandTables:
    """Tier-pure buckets: the legacy 572 feature buckets split by Hwang tier."""

    bucket_of: np.ndarray  # colex 4-card index -> bucket id
    tier_of: np.ndarray  # colex 4-card index -> tier code
    bucket_names: tuple[str, ...]
    bucket_tier: np.ndarray

    @property
    def bucket_count(self) -> int:
        return len(self.bucket_names)

    @classmethod
    def build(cls) -> HandTables:
        features = HandLookup.build()
        tiers = TierLookup.build()
        tier_codes = np.frombuffer(tiers._codes, dtype=np.uint8)
        feature_of = np.empty(HANDS4, dtype=np.int16)
        for lex, cards in enumerate(itertools.combinations(range(52), 4)):
            feature_of[colex_index(cards)] = features.combo_to_bucket[lex]
        pairs = sorted(set(zip(feature_of.tolist(), tier_codes.tolist())))
        ids = {pair: index for index, pair in enumerate(pairs)}
        bucket_of = np.fromiter(
            (ids[pair] for pair in zip(feature_of.tolist(), tier_codes.tolist())),
            dtype=np.int32,
            count=HANDS4,
        )
        names = tuple(f"{features.bucket_names[f]}|{TIERS[t]}" for f, t in pairs)
        return cls(
            bucket_of=bucket_of,
            tier_of=tier_codes.copy(),
            bucket_names=names,
            bucket_tier=np.asarray([t for _, t in pairs], dtype=np.uint8),
        )

    def tier_is_pure(self) -> bool:
        return bool(np.all(self.bucket_tier[self.bucket_of] == self.tier_of))


@dataclasses.dataclass(frozen=True)
class HandClass:
    cards: tuple[int, int, int, int]
    combos: int
    tier: str

    @property
    def text(self) -> str:
        return card_text(self.cards)


def hand_classes(tables: HandTables, tier: str | None = None) -> tuple[HandClass, ...]:
    """Suit-isomorphism classes, optionally restricted to one Hwang tier."""
    wanted = None if tier is None else TIERS.index(tier)
    counts: dict[tuple[int, ...], int] = {}
    tier_by_class: dict[tuple[int, ...], int] = {}
    for cards in itertools.combinations(range(52), 4):
        code = int(tables.tier_of[colex_index(cards)])
        if wanted is not None and code != wanted:
            continue
        key = canonical_hand(cards)
        counts[key] = counts.get(key, 0) + 1
        tier_by_class[key] = code
    return tuple(
        HandClass(key, counts[key], TIERS[tier_by_class[key]])  # type: ignore[arg-type]
        for key in sorted(counts)
    )


@dataclasses.dataclass(frozen=True)
class TreeArrays:
    """Plain numpy views of the validated static public tree."""

    actor: np.ndarray
    decision_index: np.ndarray
    children: np.ndarray
    action_ids: np.ndarray
    action_count: np.ndarray
    behind: np.ndarray
    sidepot_count: np.ndarray
    sidepot_amount: np.ndarray
    sidepot_eligible_mask: np.ndarray
    first_in_nodes: np.ndarray  # first-in decision node for seats 0..4
    decision_count: int

    @classmethod
    def build(cls) -> TreeArrays:
        tree = PublicTree.build()
        fold = ACTION_IDS["fold"]
        first_in = []
        node = 0
        for seat in range(5):
            if tree.actor[node] != seat:
                raise RuntimeError("first-in path does not reach the expected seat")
            first_in.append(node)
            slot = int(np.flatnonzero(tree.action_ids[node] == fold)[0])
            node = int(tree.children[node, slot])
        return cls(
            actor=tree.actor,
            decision_index=tree.decision_index,
            children=tree.children,
            action_ids=tree.action_ids,
            action_count=tree.action_count,
            behind=tree.behind,
            sidepot_count=tree.sidepot_count,
            sidepot_amount=tree.sidepot_amount,
            sidepot_eligible_mask=tree.sidepot_eligible_mask,
            first_in_nodes=np.asarray(first_in, dtype=np.int32),
            decision_count=tree.decision_count,
        )


def _orbit_size(cards: tuple[int, ...]) -> int:
    return len({tuple(sorted(4 * (c // 4) + perm[c % 4] for c in cards))
                for perm in itertools.permutations(range(4))})


def select_classes(
    tables: HandTables, tier: str, *, per_tier: int | None, limit: int | None, seed: int
) -> tuple[list[HandClass], list[int]]:
    """All classes of a tier, or a uniform sample of ``per_tier`` physical hands.

    Returns classes plus weights: class size for a full enumeration, or how many
    sampled physical hands fell in each class (so weighted means estimate
    combo-weighted tier averages without bias).
    """
    if per_tier is None:
        classes = list(hand_classes(tables, tier))[:limit]
        return classes, [hand.combos for hand in classes]
    code = TIERS.index(tier)
    members = [cards for cards in itertools.combinations(range(52), 4)
               if tables.tier_of[colex_index(cards)] == code]
    counts: dict[tuple[int, ...], int] = {}
    for cards in random.Random(seed).sample(members, min(per_tier, len(members))):
        key = canonical_hand(cards)
        counts[key] = counts.get(key, 0) + 1
    keys = sorted(counts)[:limit]
    return ([HandClass(k, _orbit_size(k), tier) for k in keys],  # type: ignore[arg-type]
            [counts[k] for k in keys])
