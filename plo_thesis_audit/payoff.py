"""Conservative deviation payoff and real six-seat game identity checks."""

from __future__ import annotations

from plo_chipev.game import PreflopState
from plo_chipev.showdown import settle_by_ranks
from plo_icm.game import Action

BASELINE_FOLD_EV_BB = -0.5


def conservative_increment(bb_tier: str, action: str, share: float | None) -> float:
    if bb_tier == "Trash" and action != "check":
        raise ValueError("Trash BB must free-check")
    if action == "pot":
        return -0.5
    if action != "check" or share is None or share not in (0.0, 0.5, 1.0):
        raise ValueError("check requires a showdown share of 0, 0.5, or 1")
    return 2.0 * share - 0.5


def _limped_state() -> PreflopState:
    state = PreflopState.new()
    for _ in range(4):
        state = state.apply(Action.FOLD)
    return state.apply(Action.CALL)


def real_game_increment(action: str, share: float | None) -> float:
    """Settle the actual six-seat game and subtract the SB fold terminal stack."""
    state = _limped_state()
    if action == "pot":
        state = state.apply(Action.POT).apply(Action.FOLD)
        ranks = (9, 9, 9, 9, 9, 1)
    elif action == "check" and share in (0.0, 0.5, 1.0):
        state = state.apply(Action.CHECK)
        hero_rank, bb_rank = {
            1.0: (1, 2),
            0.5: (1, 1),
            0.0: (2, 1),
        }[share]
        ranks = (9, 9, 9, 9, hero_rank, bb_rank)
    else:
        raise ValueError("invalid terminal action/share")
    final = settle_by_ranks(
        state.base.behind,
        state.base.committed,
        state.base.folded,
        ranks,
        state.base.dead_money,
    )
    fold_terminal_stack = 100.0 + BASELINE_FOLD_EV_BB
    return final[4] - fold_terminal_stack

