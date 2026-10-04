"""Card ids for Omaha 8-or-better: id = rank * 4 + suit, ranks 2..A = 0..12, suits c d h s.

This is phevaluator's order, so the same ids can be checked against it in tests.
"""

from __future__ import annotations

import re

RANKS = "23456789TJQKA"
SUITS = "cdhs"
_CARD = re.compile(r"[2-9TJQKA][cdhs]")


def card_id(text: str) -> int:
    if not _CARD.fullmatch(text):
        raise ValueError(f"invalid card {text!r}; use forms like As or 7d")
    return RANKS.index(text[0]) * 4 + SUITS.index(text[1])


def card_text(card: int) -> str:
    if not 0 <= card < 52:
        raise ValueError(f"card id must be in [0, 52), got {card}")
    return RANKS[card // 4] + SUITS[card % 4]


def card_ids(text: str) -> tuple[int, ...]:
    """Parse compact card text such as 'Ah2d3c4s'. Rejects odd lengths, bad cards and duplicates."""
    if len(text) % 2 or " " in text:
        raise ValueError(f"invalid card text {text!r}")
    cards = tuple(card_id(text[i:i + 2]) for i in range(0, len(text), 2))
    if len(set(cards)) != len(cards):
        raise ValueError(f"duplicate card in {text!r}")
    return cards
