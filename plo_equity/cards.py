"""Physical PLO4 cards and canonical global-suit isomorphism classes."""

from __future__ import annotations

import functools
import itertools
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK_SIZE = 52
PHYSICAL_HANDS = 270_725
SUIT_CLASSES = 16_432
_CARD = re.compile(r"(10|[2-9TJQKA])([cdhs])", re.IGNORECASE)
_PERMUTATIONS = tuple(itertools.permutations(range(4)))
_TRANSLATIONS = tuple(tuple(4 * (card // 4) + perm[card % 4] for card in range(DECK_SIZE))
                      for perm in _PERMUTATIONS)


@dataclass(frozen=True)
class HandClass:
    key: str
    cards: tuple[int, int, int, int]
    multiplicity: int

    @property
    def text(self) -> str:
        return card_text(self.cards)


def card_text(cards: Iterable[int]) -> str:
    return "".join(f"{RANKS[card // 4]}{SUITS[card % 4]}" for card in cards)


def parse_cards(text: str) -> tuple[int, ...]:
    compact = re.sub(r"[\s,]+", "", text).replace("10", "T")
    normalized = "".join(character.upper() if index % 2 == 0 else character.lower()
                         for index, character in enumerate(compact))
    found = _CARD.findall(compact)
    if not compact or "".join(rank.upper().replace("10", "T") + suit.lower()
                               for rank, suit in found) != normalized:
        raise ValueError(f"invalid cards {text!r}; use exact cards such as AsAhKsKh")
    cards = tuple(RANKS.index(rank.upper().replace("10", "T")) * 4
                  + SUITS.index(suit.lower()) for rank, suit in found)
    if len(set(cards)) != len(cards):
        raise ValueError("the same physical card cannot appear twice")
    return cards


def parse_hand(text: str) -> tuple[int, int, int, int]:
    cards = parse_cards(text)
    if len(cards) != 4:
        raise ValueError("a PLO4 hand must contain exactly four physical cards")
    return tuple(sorted(cards))  # type: ignore[return-value]


def canonical_hand(cards: Iterable[int]) -> tuple[int, int, int, int]:
    hand = tuple(sorted(cards))
    if len(hand) != 4 or len(set(hand)) != 4 or any(card < 0 or card >= DECK_SIZE for card in hand):
        raise ValueError("a PLO4 hand must contain four distinct deck cards")
    return min(tuple(sorted(translation[card] for card in hand))
               for translation in _TRANSLATIONS)  # type: ignore[return-value]


def class_key(cards: Iterable[int]) -> str:
    return bytes(canonical_hand(cards)).hex()


@functools.lru_cache(maxsize=1)
def enumerate_classes() -> tuple[HandClass, ...]:
    counts = Counter(canonical_hand(hand) for hand in itertools.combinations(range(DECK_SIZE), 4))
    classes = tuple(HandClass(bytes(cards).hex(), cards, multiplicity)
                    for cards, multiplicity in sorted(counts.items()))
    if len(classes) != SUIT_CLASSES or sum(hand.multiplicity for hand in classes) != PHYSICAL_HANDS:
        raise RuntimeError("PLO4 suit-class enumeration failed its complete-space invariant")
    return classes
