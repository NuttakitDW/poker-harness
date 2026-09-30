"""Readable structural features of a four-card PLO hand (cards are rank*4+suit ids)."""

from __future__ import annotations

from collections import Counter

RANKS = "23456789TJQKA"
TEN, ACE = 8, 12
SHAPES = {(2, 2): "ds", (2, 1, 1): "ss", (1, 1, 1, 1): "rb", (3, 1): "3f", (4,): "mono"}


def hand_text(cards: tuple[int, ...]) -> str:
    return "".join(RANKS[c // 4] + "cdhs"[c % 4] for c in cards)


def rank_text(cards: tuple[int, ...]) -> str:
    return "".join(sorted((RANKS[c // 4] for c in cards), key=RANKS.index, reverse=True))


def _max_in_window(ranks: set[int]) -> int:
    """Most distinct ranks inside any five-rank straight window (Ace plays high and low)."""
    values = set(ranks) | ({-1} if ACE in ranks else set())
    return max(sum(1 for r in values if low <= r <= low + 4) for low in range(-1, 9))


def features(cards: tuple[int, ...]) -> dict[str, object]:
    ranks = [c // 4 for c in cards]
    suits = [c % 4 for c in cards]
    rank_count = Counter(ranks)
    suit_count = Counter(suits)
    shape = SHAPES[tuple(sorted(suit_count.values(), reverse=True))]
    pairs = sorted((r for r, n in rank_count.items() if n == 2), reverse=True)
    if max(rank_count.values()) >= 3:
        structure = "trips"
    else:
        structure = {0: "unpaired", 1: "one_pair", 2: "two_pair"}[len(pairs)]
    suited_suits = [s for s, n in suit_count.items() if n >= 2]
    flush_tops = [max(r for r, s in zip(ranks, suits) if s == suit) for suit in suited_suits]
    best_flush = max(flush_tops) if flush_tops else -1
    if best_flush == ACE:
        flush = "nut"
    elif best_flush >= TEN:
        flush = "high"
    elif best_flush >= 0:
        flush = "low"
    else:
        flush = "none"
    distinct = set(ranks)
    return {
        "shape": shape,
        "structure": structure,
        "pair_rank": pairs[0] if pairs else -1,
        "aces": rank_count[ACE],
        "flush": flush,
        "suits_live": len(suited_suits),
        "window": _max_in_window(distinct),
        "high": sum(1 for r in ranks if r >= TEN),
        "top": max(ranks),
        "bottom": min(ranks),
        "distinct": len(distinct),
    }
