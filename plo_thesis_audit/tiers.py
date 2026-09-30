"""Validated Hwang-tier access with a full physical-hand combinadic table."""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from plo_chipev.evaluation import hwang_tier
from plo_equity.cards import canonical_hand, card_text

TIERS = ("Premium", "Speculative", "Marginal", "Trash")
TIER_TO_CODE = {tier: code for code, tier in enumerate(TIERS)}


def _physical_classifier(hand: tuple[int, ...]) -> str:
    text = card_text(hand)
    cards = tuple(text[index:index + 2] for index in range(0, 8, 2))
    return hwang_tier(cards)


@dataclass(frozen=True)
class CandidateTier:
    text: str
    hand: tuple[int, int, int, int]
    tier: str


@dataclass(frozen=True)
class CandidateValidation:
    valid: tuple[CandidateTier, ...]
    discarded: tuple[CandidateTier, ...]


def classify_candidates(texts: Iterable[str]) -> CandidateValidation:
    from .cards import parse_hand

    rows = []
    for text in texts:
        hand = parse_hand(text)
        rows.append(CandidateTier(text, hand, _physical_classifier(hand)))
    return CandidateValidation(
        valid=tuple(row for row in rows if row.tier == "Trash"),
        discarded=tuple(row for row in rows if row.tier != "Trash"),
    )


@dataclass(frozen=True)
class TierLookup:
    _codes: bytes
    deck_size: int
    build_seconds: float
    classifier_calls: int

    @classmethod
    def build(
        cls,
        *,
        deck_size: int = 52,
        classifier: Callable[[tuple[int, ...]], str] = _physical_classifier,
        canonicalize_suits: bool = True,
    ) -> TierLookup:
        if deck_size < 4 or deck_size > 52:
            raise ValueError("deck_size must be between 4 and 52")
        started = time.perf_counter()
        codes = bytearray(math.comb(deck_size, 4))
        cache: dict[tuple[int, ...], int] = {}
        calls = 0
        for hand in itertools.combinations(range(deck_size), 4):
            key = canonical_hand(hand) if canonicalize_suits and deck_size == 52 else hand
            code = cache.get(key)
            if code is None:
                tier = classifier(key)
                if tier not in TIER_TO_CODE:
                    raise RuntimeError(f"unknown tier from classifier: {tier}")
                code = TIER_TO_CODE[tier]
                cache[key] = code
                calls += 1
            codes[cls.combinadic_index(hand)] = code
        return cls(bytes(codes), deck_size, time.perf_counter() - started, calls)

    @staticmethod
    def combinadic_index(hand: tuple[int, ...]) -> int:
        cards = tuple(sorted(hand))
        if len(cards) != 4 or len(set(cards)) != 4:
            raise ValueError("tier lookup needs four distinct cards")
        return sum(math.comb(card, offset) for offset, card in enumerate(cards, 1))

    def index(self, hand: tuple[int, ...]) -> int:
        cards = tuple(sorted(hand))
        if any(card < 0 or card >= self.deck_size for card in cards):
            raise ValueError("card outside lookup deck")
        return self.combinadic_index(cards)

    def tier(self, hand: tuple[int, ...]) -> str:
        return TIERS[self._codes[self.index(hand)]]

    def __len__(self) -> int:
        return len(self._codes)

