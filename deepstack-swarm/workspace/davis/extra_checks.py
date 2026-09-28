"""Two checks the finding leans on: the deal-model error at 6 seats, and the fee.

(a) pushfold/pricer.py prices 3+ handed spots with opponents dealt independently, which its
    docstring says costs up to 0.014bb per seat against 400k real deals. The lifetime epsilon
    is 0.001bb, so this matters: 2,000,000 simulated hands shrink the standard error of the
    simulated mean to ~0.002 ICM chips and make the model error a measurement, not a footnote.
(b) Every spot in lifetime_eps.py has fee=0. GGPoker All-in or Fold charges a showdown fee
    (pushfold/spot.py; 0.2bb per player at showdown per the repo memory, unconfirmed). A fee
    is a conditional constant shift, so it moves sigma through the strategy only. One spot,
    fee 0.2, chip EV.
"""
from __future__ import annotations

import numpy as np

from pushfold import auditor, coach, hands
from pushfold.spot import Spot

from lifetime_eps import LIFETIME, Z, bubble, describe, prize_ladder, simulate


def main() -> None:
    _, p300, _ = prize_ladder("mtt_300_players.json")
    table6 = (10.0,) * 6
    P = bubble(dict(prizes=p300, players_left=46, avg_bb=20.0, table=table6))

    print("(a) 6h-10bb-ante1.0-bb-bubble46: 2,000,000 hands vs the auditor's model")
    spot = Spot(table6, ante=1.0, ante_mode="bb")
    r = coach.solve(spot, method="cfr+", target=0.001, check_every=25, max_iters=20_000,
                    payouts=P)
    net = simulate(spot, r.tree, {s: r.strategy for s in range(6)}, 2_000_000, 20260927, P)
    ref = auditor.audit(r.tree, r.strategy, payouts=P)
    print(f"    {'seat':>4} {'sim mean':>10} {'se':>8} {'model EV':>10} {'diff':>9} {'diff/se':>8}")
    for seat in range(6):
        x = net[:, seat]
        se = x.std() / np.sqrt(len(x))
        d = x.mean() - ref.ev[seat]
        print(f"    {seat:>4} {x.mean():>10.5f} {se:>8.5f} {ref.ev[seat]:>10.5f} "
              f"{d:>9.5f} {d / se:>8.2f}")
    per = describe(net)
    sigma = max(p["sigma"] for p in per)
    print(f"    sigma_max {sigma:.4f} (se {max(p['se_sigma'] for p in per):.5f}), "
          f"eps {Z * sigma / np.sqrt(LIFETIME):.6f}")

    print("\n(b) fee 0.2bb at showdown, 6h-10bb-ante1.0-bb chip EV")
    base = Spot(table6, ante=1.0, ante_mode="bb")
    for fee in (0.0, 0.2):
        s = Spot(table6, ante=1.0, ante_mode="bb", fee=fee)
        r = coach.solve(s, method="cfr+", target=0.001, check_every=25, max_iters=20_000)
        net = simulate(s, r.tree, {k: r.strategy for k in range(6)}, 200_000, 20260927)
        per = describe(net)
        sigma = max(p["sigma"] for p in per)
        dtv = float((hands.PRIOR[None, :] * np.abs(
            r.strategy[:, :, 1] - coach.solve(base, method="cfr+", target=0.001, check_every=25,
                                              max_iters=20_000).strategy[:, :, 1])
        ).sum(axis=1).max()) if fee else 0.0
        print(f"    fee {fee}: iters {r.iterations} exploit {r.exploitability:.5f} "
              f"sigma_max {sigma:.4f} eps {Z * sigma / np.sqrt(LIFETIME):.6f} "
              f"dTV vs no-fee {dtv * 100:.2f}%")


if __name__ == "__main__":
    main()
