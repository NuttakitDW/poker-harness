"""Thin validated wrapper around phevaluator's native exact PLO4 evaluator."""

from __future__ import annotations

from collections.abc import Sequence

from phevaluator import _pheval


def native_rank(hole: Sequence[int], board: Sequence[int]) -> int:
    cards = tuple(board) + tuple(hole)
    if len(hole) != 4 or len(board) != 5:
        raise ValueError("PLO4 requires four hole and five board cards")
    if len(set(cards)) != 9 or any(not isinstance(card, int) or not 0 <= card < 52 for card in cards):
        raise ValueError("cards must be nine distinct integer IDs in [0, 51]")
    return int(_pheval.evaluate_plo4_cards(*cards))


def showdown_share(hero: Sequence[int], bb: Sequence[int], board: Sequence[int]) -> float:
    if set(hero) & set(bb):
        raise ValueError("hero and BB cards overlap")
    hero_rank = native_rank(hero, board)
    bb_rank = native_rank(bb, board)
    return 1.0 if hero_rank < bb_rank else 0.0 if hero_rank > bb_rank else 0.5

