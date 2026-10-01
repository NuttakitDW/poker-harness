"""Pot-limit Omaha betting, pots, and showdown accounting for 2-9 seats.

Seats are in preflop order: 0 is first to act (UTG), then ... BTN, SB, BB. Heads-up the
button posts the small blind (seat 0) and acts first preflop, last after the flop.
"""

from __future__ import annotations

import dataclasses
import enum
import math

from .cards import winners

EPS = 1e-9


class Action(str, enum.Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE_2BB = "raise_2bb"
    POT = "pot"


def _after(seat: int, seats: set[int], n: int = 6) -> tuple[int, ...]:
    return tuple(s for step in range(1, n + 1) if (s := (seat + step) % n) in seats)


@dataclasses.dataclass(frozen=True)
class PLOState:
    initial: tuple[float, ...]
    behind: tuple[float, ...]
    committed: tuple[float, ...]
    street_put: tuple[float, ...]
    folded: frozenset[int]
    to_act: tuple[int, ...]
    acted_since_full_raise: frozenset[int]
    last_acted_bet: tuple[float, ...]
    street: int
    current_bet: float
    min_raise: float
    antes_total: float
    dead_money: float
    blind_deficit: float
    big_blind: float
    opening_raise_mode: str
    history: tuple[str, ...] = ()
    terminal: bool = False

    @classmethod
    def new(cls, stacks: tuple[float, ...], *, sb: float = .5, bb: float = 1,
            ante: float, ante_mode: str, opening_raise_mode: str = "two_bb_only") -> "PLOState":
        n = len(stacks)
        if not 2 <= n <= 9:
            raise ValueError("2-9 stacks required")
        stacks = tuple(float(x) for x in stacks)
        if ante_mode not in ("individual", "bb"):
            raise ValueError("ante_mode must be individual or bb")
        if opening_raise_mode not in ("two_bb_only", "pot_only", "both"):
            raise ValueError("opening_raise_mode must be two_bb_only, pot_only, or both")
        blind_due = (0,) * (n - 2) + (sb, bb)
        if ante_mode == "individual":
            actual_antes = tuple(min(s, ante) for s in stacks)
            left = tuple(s - a for s, a in zip(stacks, actual_antes))
            blinds = tuple(min(s, b) for s, b in zip(left, blind_due))
            behind = tuple(s - b for s, b in zip(left, blinds))
            dead_money = 0.0
            committed = tuple(a + b for a, b in zip(actual_antes, blinds))
        else:
            # TDA recommended procedure: post the live BB first, then the dead BBA from
            # what remains. This keeps a short BB eligible for the pot its blind matched.
            blinds = tuple(min(s, b) for s, b in zip(stacks, blind_due))
            left = tuple(s - b for s, b in zip(stacks, blinds))
            bb_ante = min(ante, left[n - 1])
            actual_antes = (0,) * (n - 1) + (bb_ante,)
            behind = tuple(s - a for s, a in zip(left, actual_antes))
            dead_money = bb_ante
            committed = blinds
        active = {i for i, x in enumerate(behind) if x > EPS}
        no_betting = not active
        return cls(stacks, behind, committed, blinds, frozenset(), () if no_betting else tuple(i for i in range(n) if i in active),
                   frozenset(), (0,) * n, 3 if no_betting else 0, bb, bb, sum(actual_antes), dead_money,
                   sum(blind_due) - sum(blinds),
                   bb, opening_raise_mode,
                   terminal=no_betting)

    @property
    def actor(self) -> int | None:
        return self.to_act[0] if self.to_act else None

    @property
    def seats(self) -> int:
        return len(self.initial)

    @property
    def pot(self) -> float:
        return sum(self.committed) + self.dead_money

    @property
    def live(self) -> tuple[int, ...]:
        return tuple(i for i in range(self.seats) if i not in self.folded)

    def _call_size(self, seat: int) -> float:
        return min(self.behind[seat], max(0.0, self.current_bet - self.street_put[seat]))

    def action_amount(self, action: Action) -> float:
        seat = self.actor
        if seat is None:
            raise ValueError("no actor")
        if action in (Action.FOLD, Action.CHECK):
            return 0.0
        call = self._call_size(seat)
        if action == Action.CALL:
            return call
        if action == Action.RAISE_2BB:
            if self.street != 0:
                raise ValueError("raise_2bb is preflop only")
            target = 2 * self.big_blind
            return min(self.behind[seat], max(call, target - self.street_put[seat]))
        # GG preflop pot-limit calculation omits all antes. Later streets include them.
        limit_pot = self.pot - (self.antes_total if self.street == 0 else 0.0)
        if self.street == 0:
            # TDA short-blind convention: full nominal blinds determine preflop pot-limit
            # sizing. The deficit is virtual and never enters settlement.
            limit_pot += self.blind_deficit
        target_put = self.street_put[seat] + call + limit_pot + call
        return min(self.behind[seat], max(call, target_put - self.street_put[seat]))

    def legal_actions(self) -> tuple[Action, ...]:
        seat = self.actor
        if seat is None or self.terminal:
            return ()
        facing = self.street_put[seat] + EPS < self.current_bet
        out = [Action.FOLD, Action.CALL] if facing else [Action.CHECK]
        put = self.action_amount(Action.POT)
        target = self.street_put[seat] + put
        may_reopen = (seat not in self.acted_since_full_raise
                      or self.current_bet - self.last_acted_bet[seat] + EPS >= self.min_raise)
        funded_opponent = any(i != seat and i not in self.folded and self.behind[i] > EPS for i in range(self.seats))
        raise2_put = self.action_amount(Action.RAISE_2BB) if self.street == 0 else 0.0
        raise2_target = self.street_put[seat] + raise2_put
        first_raise = self.street == 0 and self.current_bet <= self.big_blind + EPS
        can_raise2 = (self.opening_raise_mode in ("two_bb_only", "both") and first_raise
                      and raise2_target > self.current_bet + EPS
                      and may_reopen and funded_opponent)
        if can_raise2:
            out.append(Action.RAISE_2BB)
        duplicate_raise2 = can_raise2 and math.isclose(put, raise2_put, abs_tol=EPS)
        pot_open_allowed = self.opening_raise_mode in ("pot_only", "both") or not first_raise
        if (put > EPS and target > self.current_bet + EPS and may_reopen and funded_opponent
                and pot_open_allowed
                and not duplicate_raise2):
            out.append(Action.POT)
        elif (not facing and put > EPS and may_reopen and funded_opponent and pot_open_allowed
              and not duplicate_raise2):
            out.append(Action.POT)
        return tuple(out)

    def apply(self, action: Action) -> "PLOState":
        if action not in self.legal_actions():
            raise ValueError(f"illegal {action.value}; legal: {[a.value for a in self.legal_actions()]}")
        seat = self.actor
        assert seat is not None
        behind, committed, street_put = list(self.behind), list(self.committed), list(self.street_put)
        folded = set(self.folded)
        old_bet = self.current_bet
        new_bet, min_raise = old_bet, self.min_raise
        acted = set(self.acted_since_full_raise)
        last_acted = list(self.last_acted_bet)
        remaining = list(self.to_act[1:])
        if action == Action.FOLD:
            folded.add(seat)
            acted.add(seat)
        elif action == Action.CHECK:
            acted.add(seat)
        else:
            amount = self.action_amount(action)
            behind[seat] -= amount
            committed[seat] += amount
            street_put[seat] += amount
            target = street_put[seat]
            raise_size = target - old_bet
            if target > old_bet + EPS:
                new_bet = target
                active = {i for i in range(self.seats) if i not in folded and i != seat and behind[i] > EPS}
                remaining = list(_after(seat, active, self.seats))
                if raise_size + EPS >= self.min_raise:
                    min_raise = raise_size
                    acted = {seat}
                else:
                    acted.add(seat)
            else:
                acted.add(seat)
        last_acted[seat] = new_bet
        history = self.history + (f"{self.street}:{seat}:{action.value}:{street_put[seat]:.9g}",)
        live = [i for i in range(self.seats) if i not in folded]
        if len(live) == 1:
            return dataclasses.replace(self, behind=tuple(behind), committed=tuple(committed),
                street_put=tuple(street_put), folded=frozenset(folded), to_act=(), history=history,
                acted_since_full_raise=frozenset(acted), current_bet=new_bet, min_raise=min_raise,
                terminal=True)
        # Drop all-ins and any seats that became folded from the queue.
        remaining = [i for i in remaining if i not in folded and behind[i] > EPS]
        state = dataclasses.replace(self, behind=tuple(behind), committed=tuple(committed),
            street_put=tuple(street_put), folded=frozenset(folded), to_act=tuple(remaining), history=history,
            acted_since_full_raise=frozenset(acted), current_bet=new_bet, min_raise=min_raise)
        state = dataclasses.replace(state, last_acted_bet=tuple(last_acted))
        return state if remaining else state._next_street()

    def _next_street(self) -> "PLOState":
        if self.street == 3:
            return dataclasses.replace(self, terminal=True, to_act=())
        funded = {i for i in self.live if self.behind[i] > EPS}
        # With zero or one funded seat, future betting has no effect: reveal through showdown.
        if len(funded) <= 1:
            return dataclasses.replace(self, street=3, terminal=True, to_act=(), street_put=(0,) * self.seats,
                                       current_bet=0, min_raise=1)
        n = self.seats
        # SB, BB, UTG, ... after the flop; heads-up the big blind acts first.
        order = tuple(s for s in (1, 0) if s in funded) if n == 2 else _after(n - 3, funded, n)
        return dataclasses.replace(self, street=self.street + 1, to_act=order, street_put=(0,) * n,
                                   current_bet=0, min_raise=1, acted_since_full_raise=frozenset(),
                                   last_acted_bet=(0,) * n)


def settle(behind: tuple[float, ...], committed: tuple[float, ...], folded: frozenset[int],
           holes: tuple[tuple[str, ...], ...], board: tuple[str, ...], dead_money: float = 0) -> tuple[float, ...]:
    """Return final stacks, building every side pot and splitting exact ties."""
    out = list(behind)
    levels = sorted({x for x in committed if x > EPS})
    previous = 0.0
    live = tuple(i for i in range(len(committed)) if i not in folded)
    if not levels and dead_money > EPS:
        won = live if len(live) == 1 else winners(holes, board, live)
        for i in won:
            out[i] += dead_money / len(won)
    for level in levels:
        contributors = tuple(i for i, amount in enumerate(committed) if amount + EPS >= level)
        pot = (level - previous) * len(contributors) + (dead_money if previous == 0 else 0)
        eligible = tuple(i for i in contributors if i in live)
        if len(eligible) == 1:
            won = eligible
        elif eligible:
            won = winners(holes, board, eligible)
        else:
            raise RuntimeError("pot has no eligible player")
        for i in won:
            out[i] += pot / len(won)
        previous = level
    if not math.isclose(sum(out), sum(behind) + sum(committed) + dead_money, abs_tol=1e-7):
        raise RuntimeError("chip conservation failure")
    return tuple(out)
