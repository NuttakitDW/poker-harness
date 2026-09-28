"""L0 "checkdown": the flop leaf for ICM-OPEN3BET-v0, as a distribution over final stacks.

The rule. Preflop betting ends with 2 or 3 seats still holding cards and money behind.
Nobody bets again. All five board cards run out. The pot is awarded at showdown, layered by
what each seat put in; every seat keeps whatever it did not put in.

Why this shape. Under ICM a stack is worth a concave function of chips (pushfold/icm.py), so a
leaf may not return a scalar chip EV. This leaf returns, for each finishing order of the seats
that saw the flop, a whole final-stack vector for the table. pushfold/icm.py prices each vector,
and the leaf value is the sum over orders of chance x value. That is exactly the shape
pushfold/icm_pricer.py already uses for all-in showdowns.

Why no new equity tables. The flop has not been dealt when preflop betting ends, so a checkdown
runs out five unknown cards: the same distribution as a preflop all-in. The finishing-order
chances are therefore oddsmaker.two_way() heads-up and oddsmaker.orders() 3-way, unchanged.

The one interface fact. Given per-seat chips-in-the-pot, an all-in ending and a checkdown ending
are priced by *identical* code. "Everyone is all-in" is just the case invested = stack - ante.
So the tree does not need to tell the pricer which kind of ending it is; it needs to say who is
alive and how much each seat put in. See `Ending`.

Bias of L0 is stated in ../findings/leaf-model-L0.md. It is not small and it is directional.
"""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np

from pushfold import cashier, floor, icm
from pushfold.spot import Spot


@dataclasses.dataclass(frozen=True)
class Ending:
    """One ending of the preflop tree, in the only terms the pricer needs.

    alive:    seats still holding cards when preflop betting ends (1, 2 or 3).
    invested: per seat, all n of them, chips put in the pot beyond the ante. Folded seats keep
              whatever blind they posted here; it is dead money in the pot.
    """

    alive: tuple[int, ...]
    invested: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "alive", tuple(int(s) for s in self.alive))
        object.__setattr__(self, "invested", tuple(float(x) for x in self.invested))
        if not 1 <= len(self.alive) <= 3:
            raise ValueError(f"1 to 3 seats may reach the end of preflop, got {self.alive}")

    def behind(self, spot: Spot) -> tuple[float, ...]:
        """Chips each seat still has behind at the end of preflop."""
        return tuple(spot.stacks[s] - spot.antes[s] - self.invested[s] for s in range(spot.n))

    @property
    def showdown(self) -> bool:
        return len(self.alive) > 1


def settle(spot: Spot, ending: Ending) -> cashier.Settlement:
    """cashier.settle generalised from `jammers` to per-seat investment.

    Identical to pushfold/cashier.py:53-80 except that the contributions are given rather than
    derived from an all-in. With invested = cashier.contributions(spot, jammers) it reproduces
    cashier.settle exactly (tested in check_matches_cashier below).
    """
    alive = ending.alive
    paid = np.array(ending.invested, dtype=float)
    fixed = -(paid + np.array(spot.antes))
    pots: list[list] = []
    low = 0.0
    for high in sorted(set(paid[paid > 0].tolist())):
        parts = np.clip(paid - low, 0, high - low)
        eligible = tuple(s for s in alive if paid[s] >= high)
        if not eligible:
            fixed += parts                      # nobody live reached this layer: refund it
        elif len(eligible) == 1:
            fixed[eligible[0]] += parts.sum()   # uncontested
        elif pots and pots[-1][1] == eligible:
            pots[-1][0] += parts.sum()
        else:
            pots.append([parts.sum(), eligible])
        low = high
    dead = sum(spot.antes)
    if len(alive) == 1:
        fixed[alive[0]] += dead
    elif dead and pots and pots[0][1] == alive:
        pots[0][0] += dead
    elif dead:
        pots.insert(0, [dead, alive])
    if len(alive) > 1:
        fixed[list(alive)] -= spot.fee
    return cashier.Settlement(fixed, tuple(cashier.Layer(float(a), e) for a, e in pots))


def finals(spot: Spot, ending: Ending) -> dict[tuple[int, ...], np.ndarray]:
    """Final stacks of the whole table, one row per finishing order of the alive seats.

    This is the distribution the leaf emits. The chances that go with the orders come from
    the Oddsmaker and are applied by the pricer, not here.
    """
    s = settle(spot, ending)
    out = {}
    for order in itertools.permutations(ending.alive):
        net = s.net_for({seat: place + 1 for place, seat in enumerate(order)})
        out[order] = np.array(spot.stacks) + net
    return out


def worth(spot: Spot, endings: list[Ending], payouts: icm.Payouts | None,
          ) -> list[dict[tuple[int, ...], np.ndarray]]:
    """Per ending: finishing order -> value per seat, minus the value of the starting stacks.

    payouts=None gives chip EV (net chips), which is what icm_pricer does with winner-take-all.
    Same contract and same shape as pushfold/icm_pricer.py:_worth, so a plan builder can use
    either without knowing which endings are checkdowns.
    """
    keys, rows = [], []
    for index, ending in enumerate(endings):
        for order, final in finals(spot, ending).items():
            keys.append((index, order))
            rows.append(final)
    stacks = np.array(rows)
    if payouts is None:
        priced = stacks - np.array(spot.stacks)
    else:
        before = icm.value(np.array([spot.stacks]), spot.stacks, payouts)[0]
        priced = icm.value(stacks, spot.stacks, payouts) - before
    out: list[dict] = [{} for _ in endings]
    for (index, order), row in zip(keys, priced):
        out[index][order] = row
    return out


# ---------------------------------------------------------------- the sigma dial


def stackoff(spot: Spot, ending: Ending, sigma: float) -> Ending:
    """The same ending with each alive seat putting in sigma more of the contestable stack.

    sigma = 0 is L0, the checkdown: no more money goes in.
    sigma = 1 is L0-max, an automatic stack-off: every chip that two alive seats can match goes
    in, so the leaf is a preflop all-in.

    Contestable = the second largest stack behind among the alive seats: that is the most any
    two of them can match. A seat already all-in adds nothing and blocks nothing.

    This dial moves only the *spread* of the final-stack distribution, not the showdown chances.
    It is the axis ICM is most sensitive to, and both ends are exactly computable, so the chart
    spread between sigma=0 and sigma=1 is a sensitivity along that axis with no tuned parameter
    in it. It is not a bound (see ../findings/leaf-model-L0.md).
    """
    if not ending.showdown or not sigma:
        return ending
    behind = ending.behind(spot)
    live = sorted((behind[s] for s in ending.alive), reverse=True)
    room = live[1]
    extra = [sigma * min(behind[s], room) if s in ending.alive else 0.0 for s in range(spot.n)]
    return Ending(ending.alive, tuple(a + b for a, b in zip(ending.invested, extra)))


# ---------------------------------------------------------------- bridge to pushfold


def from_pushfold(tree: floor.Tree) -> list[Ending]:
    """The endings of an existing push/fold tree, in Ending form, terminal order preserved."""
    return [Ending(z.alive, tuple(cashier.contributions(tree.spot, z.jammers)))
            for z in tree.terminals]
