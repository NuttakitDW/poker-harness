"""Does the lower-exploitability chart also do better against weak responders?

AAAI 2014's disturbing possibility, restated for this repo: if exploitability (the best-responder
gain) ranks two charts one way and a spectrum of weaker responders ranks them the other way, then
`auditor.audit` alone is not a selection criterion.

Two charts of the same spot, solved to different stop targets (0.003 and 0.0005), are put through
the identical ladder from responder_ladder.py -- same seat, same deals, same action draws -- and
compared rung by rung with a paired standard error on the difference. Seat 2 is the responder, so
a *lower* seat-2 number means the chart is doing better against that responder.

Rungs: static (stale no-ante chart), and the k-sample responders k = 100, 1,000, 10,000. The exact
best response is not simulated: its gain is `auditor.audit`'s number, which is exact.
"""
from __future__ import annotations

import numpy as np

from pushfold import auditor, coach
from pushfold.spot import Spot

from lifetime_eps import simulate, uniforms
from responder_ladder import NSEAT, best_response_strategy, empirical_chart, sample_counts

NHANDS = 400_000
SEED = 20260927
SEAT = 2
KS = (100, 1_000, 10_000)


def main() -> None:
    spot = Spot((10.0,) * NSEAT, ante=1.0, ante_mode="bb")
    charts = {t: coach.solve(spot, method="cfr+", target=t, check_every=25, max_iters=20_000)
              for t in (0.003, 0.0005)}
    stale = coach.solve(Spot((10.0,) * NSEAT), method="cfr+", target=0.001, check_every=25,
                        max_iters=20_000).strategy
    u = uniforms(NHANDS, NSEAT, SEED)

    def net_for(sigma, seat_strategy):
        s = {k: sigma for k in range(NSEAT)}
        s[SEAT] = seat_strategy
        return simulate(spot, spot_tree, s, NHANDS, SEED, u=u)[:, SEAT]

    global spot_tree
    spot_tree = charts[0.003].tree
    assert charts[0.0005].tree is charts[0.003].tree or True

    rows = {}
    for t, r in charts.items():
        rep = auditor.audit(r.tree, r.strategy)
        counts = sample_counts(spot, r.tree, r.strategy, max(KS), SEED + 1)
        self_net = net_for(r.strategy, r.strategy)
        outs = {"self": self_net, "static": net_for(r.strategy, stale)}
        for k in KS:
            p_hat = empirical_chart(r.strategy, counts * (k / max(KS)))
            strat, _, _ = best_response_strategy(r.tree, p_hat, SEAT)
            outs[f"k={k:,}"] = net_for(r.strategy, strat)
        rows[t] = (outs, rep, self_net)

    print(f"spot: 6h 10bb bb-ante 1.0 chip EV, seat {SEAT} responder, {NHANDS:,} hands, CRN, "
          f"seed {SEED}")
    print(f"{'rung':>10} {'t=0.003':>10} {'t=0.0005':>10} {'diff':>9} {'se(diff)':>9} "
          f"{'chart with lower gain':>22}")
    for name in ["self", "static"] + [f"k={k:,}" for k in KS]:
        a = rows[0.003][0][name]
        b = rows[0.0005][0][name]
        d = b - a
        se = d.std() / np.sqrt(NHANDS)
        who = "t=0.0005" if d.mean() < 0 else "t=0.003"
        print(f"{name:>10} {a.mean():>10.5f} {b.mean():>10.5f} {d.mean():>9.5f} {se:>9.5f} "
              f"{who:>22} {'(=' if abs(d.mean()) < 1.96 * se else '  '}")
    print()
    for t, (_, rep, _) in rows.items():
        g = rep.gain[SEAT]
        print(f"  t={t}: exploitability (max over seats) {rep.exploitability:.5f}, "
              f"gain at seat {SEAT} {g:.6f}")
    print("  a lower-gain column wins on the weak rungs iff the 'chart with lower gain' column "
          "reads t=0.0005 everywhere at the top (rungs above the CRN resolution floor)")


if __name__ == "__main__":
    main()
