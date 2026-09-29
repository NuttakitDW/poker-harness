"""Card dealing and exact PLO-high showdown evaluation."""

from __future__ import annotations

import random
import re
import itertools

from pokerkit import Card, OmahaHoldemHand

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(r + s for r in RANKS for s in SUITS)
_CARD = re.compile(r"[2-9TJQKA][cdhs]", re.IGNORECASE)


def parse_cards(value: str | tuple[str, ...] | list[str], count: int | None = None) -> tuple[str, ...]:
    if isinstance(value, str):
        compact = value.replace(" ", "")
        if compact and len(compact) % 2:
            raise ValueError(f"invalid card text: {value!r}")
        raw = tuple(compact[i:i + 2] for i in range(0, len(compact), 2)) if len(compact) % 2 == 0 else ()
    else:
        raw = tuple(str(c) for c in value)
    if raw and not all(len(c) == 2 and _CARD.fullmatch(c) for c in raw):
        raise ValueError(f"invalid card text: {value!r}")
    cards = tuple(c[0].upper() + c[1].lower() for c in raw)
    if (count is not None and len(cards) != count) or any(not _CARD.fullmatch(c) for c in cards):
        need = f" exactly {count}" if count is not None else ""
        raise ValueError(f"cards must contain{need} valid cards like AsKd, got {value!r}")
    if len(set(cards)) != len(cards):
        raise ValueError("duplicate card")
    return cards


def deal(rng: random.Random, players: int = 6) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    cards = list(DECK)
    rng.shuffle(cards)
    holes = tuple(tuple(cards[4 * i:4 * i + 4]) for i in range(players))
    return holes, tuple(cards[4 * players:4 * players + 5])


def winners(holes: tuple[tuple[str, ...], ...], board: tuple[str, ...],
            eligible: tuple[int, ...] | None = None) -> tuple[int, ...]:
    normalized_holes = tuple(parse_cards(h, 4) for h in holes)
    normalized_board = parse_cards(board, 5)
    all_cards = tuple(c for h in normalized_holes for c in h) + normalized_board
    if len(set(all_cards)) != len(all_cards):
        raise ValueError("duplicate card across holes or board")
    eligible = eligible if eligible is not None else tuple(range(len(holes)))
    hands = {i: OmahaHoldemHand.from_game(tuple(Card.parse("".join(normalized_holes[i]))),
                                          tuple(Card.parse("".join(normalized_board)))) for i in eligible}
    best = max(hands.values())
    return tuple(i for i, hand in hands.items() if hand == best)


def canonical_cards(holes: tuple[str, ...], board: tuple[str, ...]) -> tuple[str, str]:
    """Canonicalize suit names, unordered hole cards, and the unordered flop.

    Turn and river positions stay ordered because they are distinct public histories.
    """
    candidates = []
    for renamed in itertools.permutations(SUITS):
        mapping = dict(zip(SUITS, renamed))
        transform = lambda c: c[0] + mapping[c[1]]
        private = "".join(sorted(map(transform, holes)))
        flop = sorted(map(transform, board[:3]))
        later = list(map(transform, board[3:]))
        candidates.append((private, "".join(flop + later)))
    return min(candidates)
