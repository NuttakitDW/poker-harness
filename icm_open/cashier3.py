"""Settlement from an explicit `invested` vector, and the pluggable flop-leaf interface.

`pushfold.cashier.settle` derives contributions from a set of jammers: an all-in seat put in its
whole stack, everyone else put in its blind. In OPEN3BET a seat can put in 2.2bb and keep 12.8bb,
so contributions must be given, not derived. The layering, the refund of unreachable layers, the
dead ante and the fee are copied from `pushfold.cashier.settle` unchanged, and `checked_against_pushfold`
in `verify3.py` asserts the two agree on every push/fold terminal.

LEAF MODEL INTERFACE (moravcik owns what goes in it)
---------------------------------------------------
    Leaf = Callable[[Spot, Terminal], tuple[tuple[float, Settlement], ...]]

A leaf returns a *mixture*: weights summing to 1, each with a Settlement. Under chip EV a mixture
collapses (chip EV is linear), so L0/L1/L2 cost the same. Under ICM it does not collapse: each
component is a different distribution over final stacks and must be priced separately, so the ICM
cost of a leaf model is linear in the number of mixture components. That is the price of §3 of
`bowling/open3bet-design.md`, stated up front.

`checkdown` is L0: nobody bets again, the pot is awarded at all-in equity among the seats who
reached the flop, remaining stacks stay put. It is one component, so L0 is free relative to a
preflop all-in.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from pushfold.cashier import Layer, Settlement
from pushfold.spot import Spot

from . import floor3

EPS = 1e-9
Leaf = Callable[[Spot, "floor3.Terminal"], tuple[tuple[float, Settlement], ...]]


def settle(spot: Spot, invested: tuple[float, ...], live: tuple[int, ...]) -> Settlement:
    """Layered settlement for chips already in the middle. Mirrors pushfold.cashier.settle."""
    alive = tuple(live)
    paid = np.array(invested, dtype=float)
    fixed = -(paid + np.array(spot.antes))
    pots: list[list] = []
    low = 0.0
    for high in sorted(set(paid[paid > 0].tolist())):
        parts = np.clip(paid - low, 0, high - low)
        eligible = tuple(s for s in alive if paid[s] >= high - EPS)
        if not eligible:
            fixed += parts
        elif len(eligible) == 1:
            fixed[eligible[0]] += parts.sum()
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
    return Settlement(fixed, tuple(Layer(float(a), e) for a, e in pots))


def checkdown(spot: Spot, z: "floor3.Terminal") -> tuple[tuple[float, Settlement], ...]:
    """L0: the flop leaf is a checkdown at all-in equity. One mixture component."""
    return ((1.0, settle(spot, z.invested, z.live)),)


def price_terminal(spot: Spot, z: "floor3.Terminal",
                   leaf: Leaf = checkdown) -> tuple[tuple[float, Settlement], ...]:
    """Every terminal as a mixture of settlements. Only FLOP terminals consult the leaf model."""
    if z.kind == floor3.FLOP:
        mix = leaf(spot, z)
        total = sum(w for w, _ in mix)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"leaf mixture weights sum to {total}, not 1")
        return mix
    return ((1.0, settle(spot, z.invested, z.live)),)
