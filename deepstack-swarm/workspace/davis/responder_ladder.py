"""A ladder of responders next to auditor.audit: value vs responder strength.

Davis, Burch, Bowling AAAI 2014 ("Using Response Functions to Measure Strategy Strength")
replaces the single number "exploitability" (the best responder) with a spectrum of response
functions, and asks what each one is worth against the chart. The rungs here:

  self     -- the chart against itself. The audit EV; the reference line.
  static   -- a fixed chart (solved for no ante) dropped into one seat. Does not adapt.
  k=1e2..1e5 -- a *frequentist* k-sample responder: it samples k hands of the chart's play,
              forms a smoothed empirical chart p_hat(node, class) from what it saw, and plays
              a best response to p_hat. This is the cheap analogue of CFR-UCT(k) in the 2014
              paper: a responder that is optimal against an *estimate* of the chart, not the
              chart. k -> inf recovers the exact best response.
  BR       -- auditor's best response, the top rung (exact, by construction).

Every rung is evaluated the same way: seat s plays the candidate response, every other seat
plays the chart, same deals and same action draws (CRN) across rungs. Value is seat s's
per-hand net. The ladder is worth reading as a curve of value-vs-strength, not as one number.

If the CRN pairs are correlated enough, the k-ladder gain differences are much better resolved
than any single rung's absolute value -- both are reported with standard errors.

Game: GG All-in-or-Fold, 6 seats, 10bb, bb-ante 1.0, fee 0, chip EV. Target 0.001.
"""
from __future__ import annotations

import sys

import numpy as np

from pushfold import coach, floor, icm_pricer, pricer
from pushfold.spot import Spot

from lifetime_eps import _CARD_CLASS, simulate, uniforms

NSEAT = 6
NHANDS = 400_000
SEED = 20260927
KS = (0, 100, 1_000, 10_000, 100_000)   # 0 = the uniform prior, no samples at all


def sample_counts(spot, tree, sigma, k, seed):
    """Counts of (node, class) -> action over k hands with every seat playing sigma.

    This is what a full-observation observer of the chart's play would have after k hands:
    it sees the deal and every action. (A real opponent sees less -- fold/shove is public but
    hole cards only at showdown -- so this is the optimistic rung; stated as an assumption.)
    """
    nodes_at = {(nd.seat, nd.history): nd.index for nd in tree.nodes}
    forced = set(spot.forced)
    cap = floor.MAX_ALLIN

    jam, fold = 1, 0
    rng = np.random.default_rng(seed)
    counts = np.zeros((len(tree.nodes), 169, 2))
    forced_after = [sum(1 for f in forced if f > seat) for seat in range(NSEAT)]
    for _ in range(k):

        deck = rng.permutation(52)
        hole = deck[:2 * NSEAT].reshape(NSEAT, 2)
        cls = _CARD_CLASS[hole[:, 0], hole[:, 1]]
        actions: list[int] = []
        history: tuple[int, ...] = ()
        jams = 0
        for seat in range(NSEAT):
            if seat in forced:
                actions.append(jam)
                history += (jam,)
                jams += 1
                continue
            ahead = jams + forced_after[seat]
            if (seat == NSEAT - 1 and ahead == 0) or ahead >= cap:
                break
            n = nodes_at[(seat, history)]
            p = sigma[n][cls[seat]]
            a = jam if rng.random() < p[jam] else fold
            counts[n, cls[seat], a] += 1.0
            actions.append(a)
            history += (a,)
            if a == jam:
                jams += 1
    return counts


def empirical_chart(sigma, counts, alpha=0.5):
    """Smoothed empirical action frequencies; alpha=0.5 is Jeffreys, so an unseen (node, class)
    falls back to uniform play -- a deliberately weak prior, not the chart's own value."""
    p = np.empty_like(sigma)
    tot = counts.sum(axis=2, keepdims=True)
    p[:, :, 0] = (counts[:, :, 0] + alpha) / (tot[:, :, 0] + 2 * alpha)
    p[:, :, 1] = 1.0 - p[:, :, 0]
    return p


def best_response_strategy(tree, sigma_for_pricing, seat):
    """One-hot strategy for `seat`'s nodes: the argmax of the counterfactual values."""
    cols = pricer.columns(sigma_for_pricing)
    plan = [p for p in icm_pricer.plans_for(tree, None) if p.seat == seat][0]
    cfv, _ = plan.price(cols)
    br = np.argmax(cfv, axis=2)
    out = sigma_for_pricing.copy()
    out[plan.nodes] = 0.0
    for i, n in enumerate(plan.nodes):
        out[n, np.arange(169), br[i]] = 1.0
    return out, plan, cfv


def main() -> None:
    spot = Spot((10.0,) * NSEAT, ante=1.0, ante_mode="bb")
    r = coach.solve(spot, method="cfr+", target=0.001, check_every=25, max_iters=20_000)
    sig = r.strategy
    stale = coach.solve(Spot((10.0,) * NSEAT), method="cfr+", target=0.001, check_every=25,
                        max_iters=20_000).strategy

    seat = 2                                   # a middle seat, so it has nodes with history
    u = uniforms(NHANDS, NSEAT, SEED)

    def value(strategy_seat_s):
        """All seats' per-hand net; seat `seat` plays `strategy_seat_s`, the rest the chart;
        same deals and the same action draws (CRN) at every rung."""
        s = {k: sig for k in range(NSEAT)}
        s[seat] = strategy_seat_s
        return simulate(spot, r.tree, s, NHANDS, SEED, u=u)

    others = [k for k in range(NSEAT) if k != seat]
    self_net = value(sig)
    eps = 0.001132                              # lifetime epsilon for this spot, davis-lifetime-eps.md
    print(f"seat {seat} is the responder; seats {others} play the chart. {NHANDS:,} hands, CRN.")
    print(f"chart solved to {r.exploitability:.5f} in {r.iterations} iters; lifetime eps "
          f"{eps:.6f} bb/hand")

    def line(name, net):
        g = net[:, seat] - self_net[:, seat]
        print(f"{name:>10} {net[:, seat].mean():>10.5f} {net[:, seat].std() / np.sqrt(NHANDS):>8.5f}"
              f" {g.mean():>9.5f} {g.std() / np.sqrt(NHANDS):>9.5f}"
              f" {net[:, others].mean():>12.5f}")
        return g.mean()

    print(f"{'rung':>10} {'responder':>10} {'se':>8} {'vs self':>9} {'se':>9} {'chart side':>12}")
    line("self", self_net)
    line("static", value(stale))

    br_sig, plan, _ = best_response_strategy(r.tree, sig, seat)
    br_net = value(br_sig)
    line("BR", br_net)

    # exact cross-checks, no simulation needed.
    # (i) auditing the extracted strategy must find nothing left to gain at that seat.
    from pushfold import auditor
    rep = auditor.audit(r.tree, sig)
    rep_br = auditor.audit(r.tree, br_sig)
    print(f"    exact check: audit of the extracted BR finds gain[{seat}] = "
          f"{rep_br.gain[seat]:.7f} (must be ~0); the chart's own gain there was "
          f"{rep.gain[seat]:.7f}")
    x = br_net[:, seat]
    print(f"    sim vs audit: BR value {x.mean():.5f} (se {x.std() / np.sqrt(NHANDS):.5f})"
          f" vs audit ev+gain {rep.ev[seat] + rep.gain[seat]:.5f} "
          f"(diff {x.mean() - (rep.ev[seat] + rep.gain[seat]):+.5f})")

    counts = sample_counts(spot, r.tree, sig, max(KS), SEED + 1)
    for k in KS:
        if k == 0:
            c = np.zeros_like(counts)
        else:
            c = counts * 0.0
            # emulate "only k hands seen" by scaling: counts were accumulated for max(KS)
            c = counts * (k / max(KS))
        p_hat = empirical_chart(sig, c)
        strat, _, _ = best_response_strategy(r.tree, p_hat, seat)
        line(f"k={k:,}", value(strat))
    g = br_net[:, seat] - self_net[:, seat]
    print(f"    CRN paired sd of the gain is {g.std():.2f} bb/hand, so a rung difference smaller "
          f"than {1.96 * g.std() / np.sqrt(NHANDS):.5f} is not resolved by {NHANDS:,} hands; "
          f"only the weak rungs are resolvable here.")
    print(f"    counts reached {int((counts.sum(axis=2) > 0).sum())} of {counts.shape[0] * 169} "
          f"(node, class) cells over {max(KS):,} hands")


if __name__ == "__main__":
    sys.exit(main())
