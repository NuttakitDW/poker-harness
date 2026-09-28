"""How much of the n=3 real exploit does each restricted attacker capture?

The bound is `gain(tau)` for a chosen legal `tau`; `tau` only affects tightness. Here three
candidate attackers are scored at n=3, where the exact real gain is 0.005476 (johanson, exact
joint), so the tightness of each is directly measurable:

  * `model`   -- best response to the Pricer's own prior (what the chart was solved against)
  * `onebody` -- best response to hero-conditioned marginals M[h,g] (hero-opponent card removal
                 right, opponent-opponent removal dropped): the n-independent, cheap attacker
  * `joint`   -- best response to the exact real deal (= the exact real best response at n=3)

All three are evaluated by the same simulator on the same deals, so the comparison is clean.

Usage: .venv/bin/python run_n3_attackers.py [--iters 3200] [--deals 4000000] [--seeds 2]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3]))

import adversary as adv  # noqa: E402
import cardbr  # noqa: E402
import seqbr  # noqa: E402
from pushfold import coach, floor, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--iters", type=int, default=3200)
ap.add_argument("--target", type=float, default=0.0)
ap.add_argument("--deals", type=int, default=4_000_000)
ap.add_argument("--seeds", type=int, default=2)
ap.add_argument("--mc", type=int, default=1_000_000)
args = ap.parse_args()

spot = Spot(stacks=(10.0,) * 3)
pay = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,))
res = coach.solve(spot, payouts=pay, target=args.target, max_iters=args.iters)
game = seqbr.from_floor(floor.build(spot))
sigma = res.strategy

Us = {
    "model": cardbr.analytic_values(game, sigma, pay, kind="model"),
    "onebody": cardbr.analytic_values(game, sigma, pay, kind="onebody"),
    "joint": cardbr.exact3_values(game, sigma, pay, weight="joint"),
}
for name, U in Us.items():
    rep = seqbr.audit(game, sigma, pay, U=U)
    print(f"  {name:<8} audit-on-its-own-U gain max {rep.gain.max():.6f}")

deals = [adv.real_deals(3, args.deals, seed=4242 + 17 * k) for k in range(args.seeds)]
print(f"\nchosen | evaluated on the real deal ({args.deals:,} x {args.seeds} deals)")
print("  seat  attacker      sim real gain (se)        audit-on-joint")
for s in range(3):
    ref = seqbr.audit(game, sigma, pay, U=Us["joint"]).gain[s]
    for name, U in Us.items():
        pol = adv.br_policy(game, U, s)
        gs = []
        for deals_k in deals:
            g, se = adv.sim_gain(game, sigma, s, pol, deals_k, payouts=pay)
            gs.append((g, se))
        gm = float(np.mean([g for g, _ in gs]))
        gse = float(np.sqrt(np.mean([se ** 2 for _, se in gs]) / args.seeds))
        print(f"  {s:>4}  {name:<9}  {gm:.6f} ({gse:.1e})      {ref:.6f}")
