"""Private-hand-only information abstraction for the preflop game."""

from __future__ import annotations

import json

from plo_icm.abstraction import preflop_bucket
from plo_icm.cards import canonical_cards, parse_cards

from .game import PreflopState


def hand_observation(hole: tuple[str, ...], abstraction: str) -> str:
    cards = parse_cards(hole, 4)
    if abstraction == "features":
        return preflop_bucket(cards)
    if abstraction == "exact":
        return canonical_cards(cards, ())[0]
    raise ValueError("abstraction must be features or exact")


def information_key(
    state: PreflopState,
    seat: int | None,
    hole: tuple[str, ...],
    abstraction: str,
) -> str:
    """Encode only position, own preflop hand observation, and public actions."""
    if seat is None or seat not in range(6):
        raise ValueError("seat must be from 0 through 5")
    payload = [seat, abstraction, hand_observation(hole, abstraction), list(state.history)]
    return json.dumps(payload, separators=(",", ":"))


def information_key_from_observation(
    state: PreflopState,
    seat: int | None,
    observation: str,
    abstraction: str,
) -> str:
    """Encode a cached private observation with the public action history."""
    if seat is None or seat not in range(6):
        raise ValueError("seat must be from 0 through 5")
    return json.dumps(
        [seat, abstraction, observation, list(state.history)], separators=(",", ":")
    )
