"""Native PLO4 high evaluator with PokerKit-compatible card IDs.

Cards are integers ``rank * 4 + suit`` with ranks ``234...A`` and suits ``cdhs``.
``phevaluator`` returns smaller ranks for stronger hands and its PLO4 call enforces exactly
two of four hole cards plus exactly three of five board cards.
"""

from __future__ import annotations

from collections.abc import Sequence

try:
    from phevaluator import _pheval
except ImportError as error:  # pragma: no cover - exercised only in an incomplete environment.
    raise RuntimeError("PLO equity requires phevaluator==0.6.0; install the plo-equity extra") from error


def evaluate(hole: Sequence[int], board: Sequence[int]) -> int:
    if len(hole) != 4 or len(board) != 5:
        raise ValueError("PLO4 showdown needs four hole cards and five board cards")
    cards = tuple(board) + tuple(hole)
    if any(isinstance(card, bool) or not isinstance(card, int) or not 0 <= card < 52
           for card in cards):
        raise ValueError("cards must be integer IDs from 0 through 51")
    if len(set(cards)) != 9:
        raise ValueError("hole and board cards must be distinct")
    return _evaluate_unchecked(hole, board)


def _evaluate_unchecked(hole: Sequence[int], board: Sequence[int]) -> int:
    """Fast internal boundary for simulator-generated distinct in-range integer cards."""
    return int(_pheval.evaluate_plo4_cards(*(tuple(board) + tuple(hole))))


def showdown_share(holes: Sequence[Sequence[int]], board: Sequence[int]) -> tuple[float, ...]:
    if not holes:
        raise ValueError("showdown needs at least one player")
    all_cards = tuple(board) + tuple(card for hole in holes for card in hole)
    if len(all_cards) != len(set(all_cards)):
        raise ValueError("all players and the board must use distinct physical cards")
    scores = tuple(evaluate(hole, board) for hole in holes)
    best = min(scores)
    winners = scores.count(best)
    return tuple(1.0 / winners if score == best else 0.0 for score in scores)
