"""Audit a push/fold chart under the *real* deal instead of the Pricer's independent prior.

The Pricer (`pushfold/pricer.py:20-28`) prices an opponent class g with chance `PRIOR[g]`,
independent of the hero's class and of the other opponents. Real dealing draws the hero's two
cards first and the opponents from what is left. This module computes a seat's counterfactual
value under the real deal, so `seqbr.audit` can best-respond to it.

How it works
------------
A deal enters a seat's counterfactual value only through the opponents' own action reach,
`prod_j c_j[g_j]` (the `path_columns` vectors `seqbr` builds), and the payoff of the ending. So

    u[seat, h, ending] = sum over opponent classes g of
                         D[h, g] * prod_j c_j[g_j] * Payoff(seat, ending, h, g)

with `D` the chance of the opponents' classes given the hero's class h. `Payoff` is exactly the
`cashier` + `oddsmaker` quantity `seqbr` prices: the fixed part, plus each contested layer times
the seat's equity in it (`e2`, `eq3` or `pw`), or the ICM worth of the finish order.

`Payoff` never depends on more than two opponents' classes at once -- at most 3 seats see a
showdown (`floor.MAX_ALLIN`), and a folded seat's ICM worth only needs the finish order of the
live seats -- so `D` is only ever needed on a pair. Three deal models supply it:

* `"model"`      -- each opponent ~ PRIOR (n > 2) or M (n == 2). Reproduces `seqbr.values`
  exactly; that agreement is the regression in `check_cardbr.py`.
* `"onebody"`    -- each opponent ~ M[h], the exact blocker-conditioned marginal. Right
  marginals, opponents still independent, so the two-opponent joint is M[h,g] M[h,k].
* `"joint"`      -- n = 3 only: the exact class joint `deal.joint2()`. Exact in the class
  abstraction and (suit symmetry, `deal.py`) also the exact 1326-combo value.

`mc_values()` covers n >= 4 by sampling real deals (`deal.opponent_sets`), so the only
approximation left there is Monte Carlo error plus the class abstraction.

Written by the Johanson persona (swarm agent).
"""

from __future__ import annotations

import numpy as np

import deal
import seqbr
from pushfold import hands, icm

N = len(hands.CLASSES)
PRIOR = hands.PRIOR
M = hands.M
_AXES = seqbr._AXES


# ---------------------------------------------------------------- axis plumbing


def _tab(table, pos):
    """Place the non-hero dims of `table` (hero on dim 0) at output axes `pos` of a (N, N, N) box.

    `table` is `e2` (hero, one class), `eq3`/`pw` (hero, two classes) or `orders` transposed
    (three seats, hero-shaped dim 0). `pos` gives the output axis, 0 or 1, of each extra dim.
    """
    if len(pos) == 2:
        return table.transpose(0, 2, 1) if pos == (1, 0) else table
    if len(pos) == 1:
        return table[:, :, None] if pos[0] == 0 else table[:, None, :]
    return table.reshape(N, 1, 1)


def _deal(weight: str, n: int, held: tuple[int, ...]) -> np.ndarray:
    """Chance of the `held` seats' classes given the hero class: (N,)*(1 + len(held))."""
    pair = len(held) == 2
    if weight == "joint":
        assert n == 3, "the exact two-opponent joint is built for three seats"
        J = deal.joint2()
        return J if pair else J.sum(axis=2)
    if weight == "model" and n > 2:
        if pair:
            return np.broadcast_to(PRIOR[:, None] * PRIOR[None, :], (N, N, N))
        return np.broadcast_to(PRIOR[None, :], (N, N))
    if weight not in ("model", "onebody"):
        raise ValueError(weight)
    if pair:
        return M[:, :, None] * M[:, None, :]
    return M


def _reach(weight: str, n: int, col: np.ndarray) -> np.ndarray:
    """(N,): the hero-class-indexed reach of one opponent given its class column `col`."""
    if weight == "onebody" or (weight == "model" and n == 2):
        return M @ col
    return np.broadcast_to(PRIOR @ col, (N,))


# ---------------------------------------------------------------- the payoff


def _payoff(game: seqbr.Game, seat: int, z: seqbr.Ending, leaf: seqbr.Leaf,
            worth, held: tuple[int, ...], c: np.ndarray, weight: str) -> np.ndarray:
    """(N,)*(1 + len(held)): payoff to `seat` at ending `z`, hero class first, then `held`."""
    shape = (N, N, N)
    slot = {s: k for k, s in enumerate(held)}

    def T(table, *seats):
        return _tab(table, tuple(slot[s] for s in seats))

    if worth is None:                                    # chip EV
        F = np.full(shape, float(z.settle.fixed[seat]))
        for layer in z.settle.layers:
            if seat not in layer.eligible:
                continue                                 # an ineligible layer is already in `fixed`
            rivals = [j for j in layer.eligible if j != seat]
            if len(rivals) == 2:
                F = F + layer.amount * T(leaf.eq3, rivals[0], rivals[1])
            elif len(z.alive) == 3:
                dead = next(j for j in z.alive if j not in layer.eligible)
                F = F + layer.amount * T(leaf.pw, rivals[0], dead)
            else:
                F = F + layer.amount * T(leaf.e2, rivals[0])
        return F

    w = worth[z.index]                                   # ICM worth of each finish order
    alive = z.alive
    if len(alive) == 1:
        return np.full(shape, float(w[alive][seat]))
    if len(alive) == 2:
        a, b = alive
        if seat in alive:
            rival = b if seat == a else a
            lose, win = float(w[(rival, seat)][seat]), float(w[(seat, rival)][seat])
            return np.full(shape, lose) + (win - lose) * T(leaf.e2, rival)
        below, above = float(w[(b, a)][seat]), float(w[(a, b)][seat])
        return np.full(shape, below) + (above - below) * T(leaf.e2, a, b)

    free = seat if seat in alive else alive[0]
    F = np.zeros(shape)
    for order, row in w.items():
        if row[seat] == 0.0:
            continue
        y, x = (t for t in order if t != free)
        tensor = leaf.orders.transpose(_AXES[order.index(free)])
        if free == seat:                                 # hero sits where `tensor` keeps the class
            F = F + row[seat] * T(tensor, y, x)
        elif weight == "joint":
            raise AssertionError("a folded seat with three live opponents cannot arise at n = 3")
        elif weight == "model":
            marg = np.einsum("f,fij->ij", PRIOR * c[free], tensor, optimize=True)
            F = F + row[seat] * _tab(marg[None], (slot[y], slot[x]))
        else:                                            # onebody: M[h, f] is hero-dependent
            marg = np.einsum("hf,fij,f->hij", M, tensor, c[free], optimize=True)
            F = F + row[seat] * _tab(marg, (slot[y], slot[x]))
    return F


# ---------------------------------------------------------------- which seats sit on axes


def _held(game: seqbr.Game, seat: int, z: seqbr.Ending, worth) -> tuple[int, ...]:
    """The opponents whose classes the payoff for (seat, z) depends on. Never more than two."""
    if worth is None:
        seats: set[int] = set()
        for layer in z.settle.layers:
            if seat not in layer.eligible:
                continue
            rivals = [j for j in layer.eligible if j != seat]
            seats.update(rivals)
            if len(rivals) == 1 and len(z.alive) == 3:
                seats.add(next(j for j in z.alive if j not in layer.eligible))
        return tuple(sorted(seats))
    alive = z.alive
    if len(alive) == 1:
        return ()
    if len(alive) == 2:
        return tuple(alive if seat not in alive else [j for j in alive if j != seat])
    free = seat if seat in alive else alive[0]
    return tuple(j for j in alive if j != free)


def _consumed(_game: seqbr.Game, seat: int, z: seqbr.Ending, worth) -> tuple[int, ...]:
    """Opponents whose class `_payoff` integrates out itself, so `rest` must not reach them."""
    if worth is None or seat in z.alive or len(z.alive) != 3:
        return ()
    return (z.alive[0],)                                  # the free live seat, weighted by PRIOR


def _contract(F, held, weight, n, c, seat, consumed: tuple[int, ...] = ()) -> np.ndarray:
    D = _deal(weight, n, held)
    if len(held) == 2:
        inner = np.einsum("hij,hij,i,j->h", D, F, c[held[0]], c[held[1]], optimize=True)
    elif len(held) == 1:
        inner = np.einsum("hi,hi,i->h", D, F[:, :, 0], c[held[0]], optimize=True)
    else:
        inner = np.broadcast_to(F[:, 0, 0], (N,)).astype(float)
    out = inner
    skip = set(held) | set(consumed)
    for j in range(n):
        if j != seat and j not in skip:
            out = out * _reach(weight, n, c[j])
    return out


# ---------------------------------------------------------------- public entry points


def _values(game: seqbr.Game, sigma: np.ndarray, payouts: icm.Payouts | None, leaf,
            weight: str, held_of) -> np.ndarray:
    leaf = leaf or seqbr.tables()
    n = game.spot.n
    worth = _worth_of(game, payouts)
    paths = seqbr.path_columns(game, sigma)
    U = np.zeros((n, N, len(game.endings)))
    for z in game.endings:
        c = paths[z.index]
        for seat in range(n):
            held = held_of(seat, z, worth)
            F = _payoff(game, seat, z, leaf, worth, held, c, weight)
            U[seat, :, z.index] = _contract(F, held, weight, n, c, seat,
                                            _consumed(game, seat, z, worth))
    return U


def analytic_values(game: seqbr.Game, sigma: np.ndarray, payouts: icm.Payouts | None = None,
                    leaf: seqbr.Leaf | None = None, kind: str = "model") -> np.ndarray:
    """U[seat, 169, ending] with opponents independent: `kind` = "model" (PRIOR) or "onebody" (M)."""
    return _values(game, sigma, payouts, leaf, kind,
                   lambda seat, z, worth: _held(game, seat, z, worth))


def exact3_values(game: seqbr.Game, sigma: np.ndarray, payouts: icm.Payouts | None = None,
                  leaf: seqbr.Leaf | None = None, weight: str = "joint") -> np.ndarray:
    """U[seat, 169, ending] for n = 3 under a two-opponent deal.

    `weight` names the class-pair weight: "joint" (exact `deal.joint2()`), "onebody"
    (M[h,g] M[h,k]) or "independent" (PRIOR[g] PRIOR[k]; must equal `seqbr.values`).
    Both opponents sit on axes, so card removal between them reaches every term.
    """
    assert game.spot.n == 3, "exact3_values prices three seats"
    kind = "model" if weight == "independent" else weight
    return _values(game, sigma, payouts, leaf, kind,
                   lambda seat, z, worth: tuple(j for j in range(3) if j != seat))


def _worth_of(game: seqbr.Game, payouts: icm.Payouts | None):
    return seqbr._worth(game, payouts) if payouts is not None else None


# ---------------------------------------------------------------- n >= 3, sampled


def mc_values(game: seqbr.Game, sigma: np.ndarray, payouts: icm.Payouts | None = None,
              leaf: seqbr.Leaf | None = None, samples: int = 2_000_000, seed: int = 20260927,
              chunk: int = 500_000, uniform_hero: bool = True
              ) -> tuple[np.ndarray, np.ndarray]:
    """U[seat, 169, ending] by averaging real deals. Returns (U, per-class deal count)."""
    leaf = leaf or seqbr.tables()
    n = game.spot.n
    rng = np.random.default_rng(seed)
    worth = _worth_of(game, payouts)
    paths = seqbr.path_columns(game, sigma)
    U = np.zeros((n, N, len(game.endings)))
    counts = np.zeros((n, N))
    for seat in range(n):
        others = [s for s in range(n) if s != seat]
        done = 0
        while done < samples:
            size = min(chunk, samples - done)
            done += size
            hero = (rng.integers(0, N, size=size) if uniform_hero
                    else rng.choice(N, size=size, p=PRIOR))
            opp = deal.opponent_sets(hero, n, size, rng)
            for z in game.endings:
                c = paths[z.index]
                W = np.ones(size)
                for j, s in enumerate(others):
                    W = W * c[s][opp[:, j]]
                G = _sample_payoff(game, z, seat, hero, opp, others, leaf, worth)
                U[seat, :, z.index] += np.bincount(hero, weights=W * G, minlength=N)
            counts[seat] += np.bincount(hero, minlength=N)
    return U / np.maximum(counts, 1)[:, :, None], counts


def _sample_payoff(game: seqbr.Game, z: seqbr.Ending, seat: int, hero: np.ndarray, opp: np.ndarray,
                   others: list[int], leaf: seqbr.Leaf, worth) -> np.ndarray:
    """(size,) expected payoff for `seat`, one value per sampled deal."""
    index = {s: j for j, s in enumerate(others)}
    size = len(hero)
    if worth is None:
        total = np.full(size, float(z.settle.fixed[seat]))
        for layer in z.settle.layers:
            if seat not in layer.eligible:
                continue
            rivals = [j for j in layer.eligible if j != seat]
            if len(rivals) == 2:
                total += layer.amount * leaf.eq3[hero, opp[:, index[rivals[0]]],
                                                opp[:, index[rivals[1]]]]
            elif len(z.alive) == 3:
                dead = next(j for j in z.alive if j not in layer.eligible)
                total += layer.amount * leaf.pw[hero, opp[:, index[rivals[0]]],
                                                opp[:, index[dead]]]
            else:
                total += layer.amount * leaf.e2[hero, opp[:, index[rivals[0]]]]
        return total
    w = worth[z.index]
    alive = z.alive
    if len(alive) == 1:
        return np.full(size, float(w[alive][seat]))
    if len(alive) == 2:
        a, b = alive
        if seat in alive:
            rival = b if seat == a else a
            lose, win = float(w[(rival, seat)][seat]), float(w[(seat, rival)][seat])
            return lose + (win - lose) * leaf.e2[hero, opp[:, index[rival]]]
        below, above = float(w[(b, a)][seat]), float(w[(a, b)][seat])
        return below + (above - below) * leaf.e2[opp[:, index[a]], opp[:, index[b]]]
    free = seat if seat in alive else alive[0]
    cls = {s: (hero if s == seat else opp[:, index[s]]) for s in range(game.spot.n)}
    total = np.zeros(size)
    for order, row in w.items():
        if row[seat] == 0.0:
            continue
        total += row[seat] * leaf.orders[cls[order[0]], cls[order[1]], cls[order[2]]]
    return total
