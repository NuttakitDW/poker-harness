"""The Cashier: pays out every ending of a hand.

Rules, in chips (big blinds):
* Antes are dead money. They go to the main pot, which every live player can win.
* A player who shoves puts in everything left after the ante; blinds count toward it.
* Pots are layered by contribution. A layer goes to the best hand among the live players
  who put in at least that much. A layer nobody live reached goes back to whoever paid it,
  which is how a 100bb shove against a 10bb stack plays exactly like 10bb vs 10bb.

`settle` splits each ending into a fixed part (known before the cards) and the contested
layers, so the solver only has to price the layers with the Oddsmaker's tables.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from pushfold.spot import Spot


@dataclasses.dataclass(frozen=True)
class Layer:
    amount: float
    eligible: tuple[int, ...]   # 2 or 3 live seats that can win it


@dataclasses.dataclass(frozen=True)
class Settlement:
    fixed: np.ndarray            # per seat: chips won for sure minus everything put in
    layers: tuple[Layer, ...]    # contested pots, main pot first

    def net_for(self, ranks: dict[int, int]) -> np.ndarray:
        """Net chips per seat for a known showdown. ranks: seat -> place (1 = best, ties equal)."""
        net = self.fixed.copy()
        for layer in self.layers:
            best = min(ranks[s] for s in layer.eligible)
            winners = [s for s in layer.eligible if ranks[s] == best]
            for s in winners:
                net[s] += layer.amount / len(winners)
        return net


def contributions(spot: Spot, jammers: tuple[int, ...]) -> np.ndarray:
    """Chips each seat puts in besides the ante: the whole stack if all-in, else the blind."""
    return np.array([spot.stacks[s] - spot.antes[s] if s in jammers else spot.blinds[s]
                     for s in range(spot.n)])


def settle(spot: Spot, jammers: tuple[int, ...]) -> Settlement:
    alive = jammers or (spot.n - 1,)
    paid = contributions(spot, jammers)
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
    elif dead:
        pots[0][0] += dead                      # main pot: every live seat is eligible
    return Settlement(fixed, tuple(Layer(float(a), e) for a, e in pots))
