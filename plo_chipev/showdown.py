"""Native PLO4 rank precomputation and rank-reusing side-pot settlement."""

from __future__ import annotations

import math
from collections.abc import Sequence

try:
    from phevaluator import _pheval
except ImportError as exc:  # pragma: no cover - exercised in dependency-free installs
    raise ImportError(
        "plo_chipev requires 'phevaluator'; install the project dependencies first"
    ) from exc

from plo_icm.cards import RANKS, SUITS, parse_cards

EPS = 1e-9


def _card_id(card: str) -> int:
    return RANKS.index(card[0]) * 4 + SUITS.index(card[1])


def precompute_ranks(
    holes: tuple[tuple[str, ...], ...], board: tuple[str, ...]
) -> tuple[int, ...]:
    """Evaluate every seat once; smaller native ranks are stronger."""
    if len(holes) != 6:
        raise ValueError("showdown requires six PLO4 hands")
    normalized_holes = tuple(parse_cards(hole, 4) for hole in holes)
    normalized_board = parse_cards(board, 5)
    all_cards = tuple(card for hole in normalized_holes for card in hole) + normalized_board
    if len(set(all_cards)) != len(all_cards):
        raise ValueError("duplicate card across holes or board")
    board_ids = tuple(_card_id(card) for card in normalized_board)
    return tuple(
        int(
            _pheval.evaluate_plo4_cards(
                *(board_ids + tuple(_card_id(card) for card in hole))
            )
        )
        for hole in normalized_holes
    )


def settle_by_ranks(
    behind: Sequence[float],
    committed: Sequence[float],
    folded: frozenset[int],
    ranks: Sequence[int],
    dead_money: float = 0.0,
) -> tuple[float, ...]:
    """Settle every side pot while reusing one precomputed rank per seat."""
    if not (len(behind) == len(committed) == len(ranks)):
        raise ValueError("behind, committed, and ranks must have equal lengths")
    out = [float(value) for value in behind]
    levels = sorted({float(value) for value in committed if value > EPS})
    live = tuple(seat for seat in range(len(committed)) if seat not in folded)
    previous = 0.0

    def winners(eligible: tuple[int, ...]) -> tuple[int, ...]:
        best = min(ranks[seat] for seat in eligible)
        return tuple(seat for seat in eligible if ranks[seat] == best)

    if not levels and dead_money > EPS:
        won = live if len(live) == 1 else winners(live)
        for seat in won:
            out[seat] += dead_money / len(won)
    for level in levels:
        contributors = tuple(
            seat for seat, amount in enumerate(committed) if amount + EPS >= level
        )
        pot = (level - previous) * len(contributors)
        if previous == 0:
            pot += dead_money
        eligible = tuple(seat for seat in contributors if seat in live)
        if not eligible:
            raise RuntimeError("pot has no eligible player")
        won = eligible if len(eligible) == 1 else winners(eligible)
        for seat in won:
            out[seat] += pot / len(won)
        previous = level
    expected = sum(behind) + sum(committed) + dead_money
    if not math.isclose(sum(out), expected, abs_tol=1e-7):
        raise RuntimeError("chip conservation failure")
    return tuple(out)
