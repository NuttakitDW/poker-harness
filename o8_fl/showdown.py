"""Hi-lo pot splitting at showdown, heads-up, from player 0's side."""

from __future__ import annotations

from numba import njit

from .evaluator import NO_LOW


@njit(cache=True)
def _share(mine: float, theirs: float, higher_wins: bool) -> float:
    if mine == theirs:
        return 0.5
    return 1.0 if (mine > theirs) == higher_wins else 0.0


@njit(cache=True)
def showdown_net(each: float, high0: int, high1: int, low0: int, low1: int) -> float:
    """Net chips for player 0 when both put `each` in. High: larger wins. Low: smaller wins, NO_LOW never does.

    With no qualifying low the high hand takes the whole pot; otherwise each half is split on its own, so
    tied halves quarter the pot.
    """
    pot = 2.0 * each
    if low0 == NO_LOW and low1 == NO_LOW:
        return pot * _share(high0, high1, True) - each
    half = pot / 2.0
    return half * _share(high0, high1, True) + half * _share(low0, low1, False) - each
