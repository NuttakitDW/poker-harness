"""CFR-f on a 2-seat spot: train a chart against a k-sample responder, price the trade.

AAAI 2014 ("Using Response Functions to Measure Strategy Strength") §4 and Davis's MSc thesis
(2015) §4 define CFR-f: counterfactual regret minimization where the opponent is not the
equilibrium opponent but a *response function* f of our own strategy -- here a responder that
samples k hands of our play, forms a smoothed empirical chart p_hat from them, and best-responds
to p_hat. The thesis covers the stochastic case (a randomly drawn f), which is what a sampled
p_hat is.

Heads-up 10bb is the smallest spot where this is meaningful and where every number here is
*exact* rather than simulated: with 2 seats, 2 decision nodes (seat 0 acts first; seat 1 acts
only after a jam) and 169 classes per node, the pricer gives counterfactual values in closed
form, so a chart's value against a fixed responder is a weighted sum with no Monte Carlo error.
The only randomness is the k hands the responder samples.

What is reported, per k and per responder seed:
  g      -- exploitability of the chart (exact BR gain at the other seat, 2-player zero-sum)
  v_k    -- the chart's exact value against that k-sample responder
and the baseline chart (coach.solve at target 0.001) for comparison. The claim to test is the
2014 one: the trained chart should buy v_k at a measurable cost in g, and the trade should be
quoted as a rate, not a slogan.
"""
from __future__ import annotations

import sys

import numpy as np

from pushfold import auditor, coach, hands, icm_pricer, pricer
from pushfold.spot import Spot

SPOT = Spot((10.0, 10.0))
LEARNER, RESP = 0, 1
ROUNDS = 400
ALPHA = 0.5
SEEDS = (11, 22, 33, 44, 55)
KS = (100, 1_000)


def build(spot):
    tree = coach.solve(spot, method="cfr+", target=0.001, check_every=25,
                       max_iters=20_000).tree
    plans = {p.seat: p for p in icm_pricer.plans_for(tree, None)}
    return tree, plans


def value_of(tree, plans, mine, theirs, seat=LEARNER):
    """Exact per-hand value for `seat` when it plays `mine` and the other seat plays `theirs`."""
    sigma = np.zeros((len(tree.nodes), 169, 2))
    p = plans[seat]
    sigma[p.nodes] = mine
    for s, strat in theirs.items():
        sigma[plans[s].nodes] = strat
    cfv, fixed = p.price(pricer.columns(sigma))
    now = (mine * cfv).sum(axis=2)
    return float(hands.PRIOR @ (now.sum(axis=0) + fixed)), sigma


def exploitability(tree, plans, mine, ref, v_resp_star):
    """Exploitability of the learner's chart in this 2-seat game.

    max_{sigma_resp} u_resp(mine, sigma_resp) - v_resp*, where v_resp* is the game value for the
    responder. The max is `ref`'s value plus the audit gain over `ref`; the gain reported by
    auditor.audit is measured *relative to whatever strategy the sigma array holds* at that
    seat, so `ref` (the solved chart's own seat-1 strategy) is the reference, not 0.5/0.5.
    """
    v_ref, sigma = value_of(tree, plans, ref, {LEARNER: mine}, seat=RESP)
    gain = float(auditor.audit(tree, sigma, plans=[plans[LEARNER], plans[RESP]]).gain[RESP])
    return v_ref + gain - v_resp_star


def sample_empirical(sigma0, k, rng):
    """Smoothed empirical chart of the learner's node-0 strategy from k sampled hands."""
    cls = rng.choice(169, size=k, p=hands.PRIOR)
    jam = rng.random(k) < sigma0[cls, 1]
    counts = np.zeros((169, 2))
    np.add.at(counts, (cls[jam], 1), 1.0)
    np.add.at(counts, (cls[~jam], 0), 1.0)
    tot = counts.sum(axis=1, keepdims=True)
    p = (counts[:, :1] + ALPHA) / (tot + 2 * ALPHA)
    return np.hstack([1.0 - p, p])


def response(tree, plans, sigma0, k, rng):
    """The responder: exact best response to the empirical chart from k sampled hands."""
    p_hat = sample_empirical(sigma0, k, rng)
    sigma = np.zeros((len(tree.nodes), 169, 2))
    sigma[plans[LEARNER].nodes] = p_hat
    sigma[plans[RESP].nodes] = 0.5
    cfv, _ = plans[RESP].price(pricer.columns(sigma))
    br = np.argmax(cfv, axis=2)[0]
    out = np.zeros((169, 2))
    out[np.arange(169), br] = 1.0
    return out


def cfr_f(tree, plans, sigma0_init, k, seed, rounds=ROUNDS, block=10):
    """CFR-f: regret matching for the learner against a responder recomputed every `block`
    iterations from the learner's *current* strategy (a stochastic response function)."""
    rng = np.random.default_rng(seed)
    regret = np.zeros((169, 2))
    avg = np.zeros((169, 2))
    sigma = sigma0_init.copy()
    for t in range(rounds):
        if t % block == 0:
            theirs = response(tree, plans, sigma, k, rng)
            _, full = value_of(tree, plans, sigma, {RESP: theirs})
            cfv, _ = plans[LEARNER].price(pricer.columns(full))
            cfv0 = cfv[0]                                   # (169, 2), fixed while blocked
        regret += cfv0 - (sigma * cfv0).sum(axis=1, keepdims=True)   # CFR+ style, no averaging
        np.maximum(regret, 0.0, out=regret)
        tot = regret.sum(axis=1, keepdims=True)
        sigma = np.where(tot > 0, regret / np.where(tot > 0, tot, 1.0), 0.5)
        avg += sigma
    return avg / rounds


def main() -> None:
    tree, plans = build(SPOT)
    base = coach.solve(SPOT, method="cfr+", target=0.001, check_every=25, max_iters=20_000)
    sigma_star = base.strategy[plans[LEARNER].nodes[0]]          # (169, 2)
    ref = base.strategy[plans[RESP].nodes[0]]                    # the solved seat-1 chart
    v0_star, _ = value_of(tree, plans, sigma_star, {RESP: ref}, seat=LEARNER)
    v1_star = -v0_star                                           # zero-sum, fee 0
    g0 = exploitability(tree, plans, sigma_star, ref, v1_star)
    print(f"HU 10bb chip EV, no ante. Learner = seat {LEARNER}, responder = seat {RESP}.")
    print(f"baseline chart: game value v0* = {v0_star:.5f}, exploitability g0 = {g0:.6f} "
          f"bb/hand (audit max over seats {base.exploitability:.6f})")
    print(f"{'k':>6} {'seed':>5} {'v_k(base)':>10} {'v_k(cfr-f)':>11} {'g(cfr-f)':>9} "
          f"{'gain':>8} {'dG':>8}")
    for k in KS:
        vb = []
        for seed in SEEDS:
            rng = np.random.default_rng(seed)
            theirs = response(tree, plans, sigma_star, k, rng)
            vb.append(value_of(tree, plans, sigma_star, {RESP: theirs})[0])
        print(f"{k:>6} {'mean':>5} {np.mean(vb):>10.5f} {'':>11} {'':>9} {'':>8} {'':>8}"
              f"   (v_k of baseline over {len(SEEDS)} responder seeds, "
              f"sd {np.std(vb):.5f})")
        for seed in SEEDS:
            trained = cfr_f(tree, plans, sigma_star, k, seed)
            theirs = response(tree, plans, trained, k, np.random.default_rng(seed))
            v = value_of(tree, plans, trained, {RESP: theirs})[0]
            g = exploitability(tree, plans, trained, ref, v1_star)
            print(f"{k:>6} {seed:>5} {'':>10} {v:>11.5f} {g:>9.5f} {v - np.mean(vb):>8.5f} "
                  f"{g - g0:>8.5f}")

    # The spectrum: what does a chart trained for one responder class do against the others?
    # The trained chart is the k=1000 one; "BR" is the exact best responder (exploitability).
    trained = cfr_f(tree, plans, sigma_star, 1_000, SEEDS[0])
    print(f"\nlearner's value against each responder class (mean over {len(SEEDS)} seeds; "
          f"BR column is exact and seed-free, zero-sum so u0 = -u1)")
    print(f"{'chart':>10} {'k=0':>9} {'k=100':>9} {'k=1,000':>9} {'k=10,000':>9} {'BR':>9} "
          f"{'exploit':>9}")
    for name, chart in (("baseline", sigma_star), ("cfr-f k=1e3", trained)):
        row = []
        for k in (0, 100, 1_000, 10_000):
            vs = [value_of(tree, plans, chart, {RESP: response(tree, plans, chart, k, rng)})[0]
                  for rng in (np.random.default_rng(s) for s in SEEDS)]
            row.append(np.mean(vs))
        g = exploitability(tree, plans, chart, ref, v1_star)
        print(f"{name:>10} " + " ".join(f"{x:>9.5f}" for x in row) +
              f" {-(v1_star + g):>9.5f} {g:>9.5f}")


if __name__ == "__main__":
    sys.exit(main())
