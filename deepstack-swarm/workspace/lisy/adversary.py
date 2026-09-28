"""A sound lower bound on real-deal exploitability, LBR style (Lisy & Bowling, AAAI-W 2017).

Why this file exists
--------------------
`pushfold/auditor.py` reports the best-response gain *inside the Pricer's deal model*
(independent opponent priors at 3+ seats, `pushfold/pricer.py:20-28`). `johanson`'s
`cardbr.py` re-prices the same chart under the real deal and finds the real gain is
90-3100x the model one (`findings/johanson-model-vs-real-gap.md`). Two things are missing
from that number:

  * It is a **plug-in estimate**, not one-sided. `cardbr.mc_values` estimates the
    counterfactual values U[seat,h,ending]; `seqbr.audit` then takes a max against that
    noisy U, which the max-of-noisy-estimates effect biases *upward*, and nothing in it
    bounds the true best-response gain from either side.
  * Nothing says which side of the true value it is on, so a reader cannot tell "the chart
    is at least this exploitable" from "the chart is about this exploitable".

LBR's own lesson (Lisy & Bowling 2017, Sec. 2) is that an exact best response is not needed
for a *sound* number: **any legal strategy's winnings against a fixed opponent lower-bound
that opponent's exploitability**, because the best response wins at least as much. LBR is
such a strategy, chosen cheaply and evaluated honestly.

What this file builds
---------------------
For a fixed chart `sigma` and a chosen attacker seat `s`:

    gain(tau) = E_real[ u_s(tau, sigma_{-s}) ] - E_real[ u_s(sigma) ]   <=   real BR gain

for any legal `tau`. Two pieces:

1. `br_policy(game, U, seat)` -- a sequential best response (argmax per information set) to
   *any* counterfactual-value tensor `U`. With the exact real-deal U this is the exact real
   best response; with an approximate U it is just *a* strategy and the bound stays sound.
   `U` affects tightness only. `model` (the Pricer's own prior) gives a vacuous attacker;
   `onebody` (hero-conditioned marginals) and `pairjoint` (exact two-opponent joint, rest
   independent given the hero) are the cheap informative ones.

2. `sim_gain(...)` -- evaluates a profile under the real deal by a full tree walk, one pass
   per deal, with the acting seat's action *marginalised* rather than sampled. Deals are
   shared between the two profiles (common random numbers), so the estimator is a paired
   difference and the only noise is over deals. The actions are marginalised because
   otherwise the strategy's own randomisation would be most of the error bar in a
   push/fold-shaped tree, and that is not what the model-vs-real question is about.

Soundness and the interval. `gain(tau)` is a lower bound on the seat's real best-response
gain *exactly*, not in expectation. What is estimated is only the mean of an i.i.d. per-deal
difference; the 95% interval is the ordinary normal one, and `bound()` returns the lower end
of it (optionally Bonferroni-corrected over a set of candidate attackers), which is a
one-sided bound with the stated confidence. Per-deal payoffs are bounded by the largest
stack, so the estimator is well behaved.

Verified at n = 3, where the exact real U exists (`cardbr.exact3_values(weight="joint")`,
both opponents on axes, no independence anywhere): the simulator reproduces johanson's exact
real gains (see `run_n3_validate.py`), which makes it a second derivation, not a new number.

Written by the Lisy persona (swarm agent). Nothing in `pushfold/` was modified.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_JOHANSON = _HERE.parent / "johanson"
_OPEN3BET = _HERE.parent / "burch" / "open3bet"
for _p in (str(_HERE.parents[2]), str(_JOHANSON), str(_OPEN3BET)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cardbr  # noqa: E402  (johanson)
import deal  # noqa: E402
import seqbr  # noqa: E402

N = seqbr.N
PRIOR = seqbr.PRIOR


# ---------------------------------------------------------------- real deals


def real_deals(n: int, samples: int, seed: int = 0,
               rng: np.random.Generator | None = None) -> np.ndarray:
    """(samples, n) hand-class indices under the real deal: hero ~ PRIOR, the rest from the deck."""
    rng = rng if rng is not None else np.random.default_rng(seed)
    hero = rng.choice(N, size=samples, p=PRIOR).astype(np.int64)
    opp = deal.opponent_sets(hero, n, samples, rng)
    return np.concatenate([hero[:, None], opp], axis=1)


# ---------------------------------------------------------------- attacker models (approximate U)


def pair_values(game: seqbr.Game, sigma: np.ndarray, payouts=None, leaf: seqbr.Leaf | None = None
                ) -> np.ndarray:
    """`cardbr.analytic_values` with the exact two-opponent joint instead of independence.

    Two opponents' classes are drawn from the real deal without replacement, so their chance
    given the hero is `deal.joint2()`, not `M[h,g] M[h,k]`. Payoffs here never depend on more
    than two opponents at once (at most three seats see a showdown, `floor.MAX_ALLIN`), so
    this is the right pairwise chance; opponents beyond the two the payoff touches are still
    treated as independent given the hero, which is the approximation that remains. At n = 3
    there are no "rest" opponents and this *is* the exact real deal.

    Implemented by swapping `cardbr._deal` for the duration of one call, so the payoff and
    contraction code staying tested is johanson's, unmodified.
    """
    onebody = cardbr._deal

    def _deal(weight: str, n: int, held: tuple[int, ...]) -> np.ndarray:
        J = deal.joint2()
        return J if len(held) == 2 else J.sum(axis=2)

    cardbr._deal = _deal
    try:
        return cardbr.analytic_values(game, sigma, payouts, leaf, kind="onebody")
    finally:
        cardbr._deal = onebody


ATTACKER_MODELS = ("model", "onebody", "pairjoint")


def attacker_u(game: seqbr.Game, sigma: np.ndarray, payouts, which: str,
               leaf: seqbr.Leaf | None = None) -> np.ndarray:
    if which == "model":
        return cardbr.analytic_values(game, sigma, payouts, leaf, kind="model")
    if which == "onebody":
        return cardbr.analytic_values(game, sigma, payouts, leaf, kind="onebody")
    if which == "pairjoint":
        return pair_values(game, sigma, payouts, leaf)
    raise ValueError(which)


# ---------------------------------------------------------------- the best response


def br_policy(game: seqbr.Game, U: np.ndarray, seat: int) -> np.ndarray:
    """(nodes, 169) int8: at each of `seat`'s nodes the arg-max action per hand class, -1 elsewhere.

    Backward induction with the max at the seat's own nodes only -- the same recursion
    `seqbr._walk(best=True)` runs, with the argmax recorded. Per information set
    (public history, hand class), which in this tree is (node, class).
    """
    pol = np.full((len(game.nodes), N), -1, dtype=np.int8)

    def go(index: int) -> np.ndarray:
        if index < 0:
            return U[seat, :, ~index]
        node = game.nodes[index]
        kids = np.stack([go(child) for child in node.children], axis=1)
        if node.seat != seat:
            return kids.sum(axis=1)
        pol[node.index] = kids.argmax(axis=1)
        return kids.max(axis=1)

    go(game.root)
    return pol


# ---------------------------------------------------------------- profile evaluation


def profile_ev(game: seqbr.Game, deals: np.ndarray, sigma: np.ndarray, seat: int,
               attacker: int | None = None, policy: np.ndarray | None = None,
               leaf: seqbr.Leaf | None = None, payouts=None) -> np.ndarray:
    """(samples,): per-deal expected payoff to `seat` under the profile.

    Full tree walk, the acting seat's action *marginalised* (exact given the deal and the
    profile, so the only randomness is the deal). Each terminal is visited once, so no
    (endings x samples) table is ever materialised. `policy` is used at `attacker`'s nodes.
    """
    leaf = leaf or seqbr.tables()
    worth = cardbr._worth_of(game, payouts)
    others = [s for s in range(game.spot.n) if s != seat]
    hero = deals[:, seat]
    opp = deals[:, others]
    size = len(deals)

    def payoff(index: int) -> np.ndarray:
        return cardbr._sample_payoff(game, game.endings[index], seat, hero, opp, others,
                                     leaf, worth)

    def go(index: int, prob: np.ndarray) -> np.ndarray:
        if index < 0:
            return prob * payoff(~index)
        node = game.nodes[index]
        cls = deals[:, node.seat]
        total = np.zeros(size)
        if attacker is not None and node.seat == attacker:
            chosen = policy[node.index][cls]
            for k, child in enumerate(node.children):
                p = (chosen == k).astype(float)
                if p.any():
                    total += go(child, prob * p)
        else:
            for k, child in enumerate(node.children):
                p = sigma[node.index, :, k][cls]
                if p.any():
                    total += go(child, prob * p)
        return total

    return go(game.root, np.ones(size))


def _pooled(chunks: list[tuple[int, float, float]]) -> tuple[float, float]:
    """Pooled mean and its standard error from per-chunk (n, mean, sample variance)."""
    ns = np.array([c[0] for c in chunks], dtype=float)
    ms = np.array([c[1] for c in chunks])
    vs = np.array([c[2] for c in chunks])
    total = ns.sum()
    mean = float((ns * ms).sum() / total)
    within = float(((ns - 1) * vs).sum())
    between = float((ns * (ms - mean) ** 2).sum())
    var = (within + between) / max(total - 1, 1)
    return mean, float(np.sqrt(var / total))


def deal_chunks(n: int, total: int, seed: int, chunk: int = 250_000):
    rng = np.random.default_rng(seed)
    done = 0
    while done < total:
        size = min(chunk, total - done)
        done += size
        yield real_deals(n, size, rng=rng)


def sim_gain(game: seqbr.Game, sigma: np.ndarray, seat: int, policy: np.ndarray,
             total_deals: int, seed: int, chunk: int = 250_000,
             leaf: seqbr.Leaf | None = None, payouts=None
             ) -> dict:
    """Paired real-deal estimate of `gain(policy)` for `seat`, with the chart's own real EV.

    Common random numbers: the same deals evaluate both profiles, so the estimate is the mean
    of a per-deal difference. Returns the gain, its se, the chart's EV and its se.
    """
    gc: list[tuple[int, float, float]] = []
    ec: list[tuple[int, float, float]] = []
    for deals in deal_chunks(game.spot.n, total_deals, seed, chunk):
        base = profile_ev(game, deals, sigma, seat, leaf=leaf, payouts=payouts)
        alt = profile_ev(game, deals, sigma, seat, seat, policy, leaf, payouts)
        d = alt - base
        gc.append((len(d), float(d.mean()), float(d.var(ddof=1))))
        ec.append((len(base), float(base.mean()), float(base.var(ddof=1))))
    g, gse = _pooled(gc)
    e, ese = _pooled(ec)
    return {"gain": g, "se": gse, "ev": e, "ev_se": ese, "deals": total_deals}


def bound(cands: list[dict], confidence: float = 0.95) -> tuple[float, int]:
    """Lower end of the interval for `max_k gain_k`: (bound, index of the best candidate).

    Bonferroni over the candidate set, so the coverage claim is about the max, not about any
    single attacker.
    """
    k = len(cands)
    z = _z(1.0 - (1.0 - confidence) / k)
    adj = [c["gain"] - z * c["se"] for c in cands]
    best = int(np.argmax(adj))
    return float(adj[best]), best


def _z(p: float) -> float:
    """Standard normal quantile, no scipy."""
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _phi(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _phi(x: float) -> float:
    from math import erf, sqrt
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))
