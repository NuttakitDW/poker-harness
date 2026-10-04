"""Heads-up fixed-limit betting. Seat 0 is the button and small blind, seat 1 the big blind.

Actions: f fold, k check, c call, b bet, r raise. Preflop the big blind counts as the first bet, so a
cap of 5 allows four raises preflop and a bet plus four raises after the flop.
"""

from __future__ import annotations

import dataclasses

STREETS = 4


@dataclasses.dataclass(frozen=True)
class Rules:
    small_blind: float = 0.5
    big_blind: float = 1.0
    small_bet: float = 1.0  # preflop and flop
    big_bet: float = 2.0  # turn and river
    cap: int = 5

    def __post_init__(self) -> None:
        if self.cap < 2:
            raise ValueError("cap must allow at least one raise")
        if not 0 < self.small_blind <= self.big_blind <= self.small_bet <= self.big_bet:
            raise ValueError("need 0 < small blind <= big blind <= small bet <= big bet")

    def bet_size(self, street: int) -> float:
        return self.small_bet if street < 2 else self.big_bet


@dataclasses.dataclass(frozen=True)
class BettingState:
    rules: Rules
    street: int
    committed: tuple[float, float]
    street_put: tuple[float, float]
    bets: int
    actor: int
    acted: frozenset[int]
    history: str = ""
    terminal: bool = False
    folder: int | None = None

    @classmethod
    def new(cls, rules: Rules = Rules()) -> BettingState:
        blinds = (rules.small_blind, rules.big_blind)
        return cls(rules, 0, blinds, blinds, 1, 0, frozenset())

    def legal(self) -> str:
        if self.terminal:
            return ""
        facing = self.street_put[self.actor] < max(self.street_put)
        can_raise = self.bets < self.rules.cap
        if facing:
            return "fcr" if can_raise else "fc"
        if self.bets == 0:
            return "kb"
        return "kr" if can_raise else "k"

    def apply(self, action: str) -> BettingState:
        if action not in self.legal() or len(action) != 1:
            raise ValueError(f"illegal action {action!r} after {self.history!r}; legal: {self.legal()!r}")
        me, other = self.actor, 1 - self.actor
        history = self.history + action
        if action == "f":
            return dataclasses.replace(self, history=history, terminal=True, folder=me)
        put = list(self.street_put)
        bets = self.bets
        acted = self.acted | {me}
        if action == "c":
            put[me] = put[other]
        elif action in "br":
            put[me] = max(put) + self.rules.bet_size(self.street)
            bets += 1
            acted = frozenset({me})
        added = put[me] - self.street_put[me]
        committed = list(self.committed)
        committed[me] += added
        state = dataclasses.replace(self, committed=tuple(committed), street_put=tuple(put), bets=bets,
                                    actor=other, acted=acted, history=history)
        closed = len(acted) == 2 and put[0] == put[1]
        return state._next_street() if closed else state

    def _next_street(self) -> BettingState:
        if self.street == STREETS - 1:
            return dataclasses.replace(self, terminal=True)
        return dataclasses.replace(self, street=self.street + 1, street_put=(0.0, 0.0), bets=0, actor=1,
                                   acted=frozenset())
