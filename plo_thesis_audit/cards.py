"""Physical-card parsing and fixed-hero conditional dealing."""

from __future__ import annotations

import random
from dataclasses import dataclass

from plo_equity.cards import parse_hand as _parse_hand

DECK = tuple(range(52))


def parse_hand(text: str) -> tuple[int, int, int, int]:
    """Parse and sort one exact four-card PLO hand."""
    return _parse_hand(text)


@dataclass(frozen=True)
class Deal:
    earlier_holes: tuple[tuple[int, ...], ...]
    bb_hole: tuple[int, ...]
    board: tuple[int, ...]


def full_deal(rng: random.Random, hero: tuple[int, ...]) -> Deal:
    """Deal four prior hands, BB, and board without replacement, excluding hero."""
    if len(hero) != 4 or len(set(hero)) != 4 or any(card not in DECK for card in hero):
        raise ValueError("hero must contain four distinct physical cards")
    remaining = tuple(card for card in DECK if card not in hero)
    dealt = rng.sample(remaining, 25)
    earlier = tuple(tuple(dealt[offset:offset + 4]) for offset in range(0, 16, 4))
    return Deal(earlier, tuple(dealt[16:20]), tuple(dealt[20:25]))

