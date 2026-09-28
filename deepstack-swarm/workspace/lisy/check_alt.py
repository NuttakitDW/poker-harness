"""Decisive check of the simulator: one profile value, two independent routes.

Route A: `adversary.profile_ev` on real deals (cardbr._sample_payoff per terminal).
Route B: `cardbr.exact3_values(weight="joint")` + `seqbr._walk(best=False)` on the *modified*
strategy -- the analytic path johanson's check_mc_gain tests.

Both price the same profile, so they must agree to Monte Carlo error. This isolates the payoff
functions from the best-response (max) step, which the 100M-deal bias run did not.

Usage: .venv/bin/python check_alt.py [--deals 30000000]
"""
from __future__ import annotations

import argparse
import sys
import time
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
ap.add_argument("--deals", type=int, default=30_000_000)
ap.add_argument("--chunk", type=int, default=500_000)
ap.add_argument("--seat", type=int, default=0)
args = ap.parse_args()

spot = Spot(stacks=(10.0,) * 3)
pay = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,))
game = seqbr.from_floor(floor.build(spot))
sigma = coach.solve(spot, payouts=pay, target=0.0, max_iters=3200).strategy

U = cardbr.exact3_values(game, sigma, pay, weight="joint")
pol = adv.br_policy(game, U, args.seat)
prime = sigma.copy()
for i in range(len(game.nodes)):
    if pol[i][0] >= 0:
        for k in range(prime.shape[2]):
            prime[i, :, k] = (pol[i] == k).astype(float)

U2 = cardbr.exact3_values(game, prime, pay, weight="joint")
b = float(seqbr.PRIOR @ seqbr._walk(game, U2[args.seat], prime, args.seat, best=False))
a0 = float(seqbr.PRIOR @ seqbr._walk(game, U[args.seat], sigma, args.seat, best=False))
print(f"route B (analytic): base {a0:.6f}  alt {b:.6f}  gain {b-a0:.6f}")

ec = []
t0 = time.perf_counter()
for deals in adv.deal_chunks(3, args.deals, seed=919, chunk=args.chunk):
    base = adv.profile_ev(game, deals, sigma, args.seat, payouts=pay)
    alt = adv.profile_ev(game, deals, sigma, args.seat, args.seat, pol, payouts=pay)
    ec.append((len(base), float(base.mean()), float(base.var(ddof=1))))
    ec.append((len(alt), float(alt.mean()), float(alt.var(ddof=1))))
a, ase = adv._pooled(ec[0::2])
c, cse = adv._pooled(ec[1::2])
print(f"route A (simulated, {args.deals:,} deals): base {a:.6f} (se {ase:.1e})  "
      f"alt {c:.6f} (se {cse:.1e})  gain {c-a:.6f}")
print(f"  base z={(a-a0)/ase:+.2f}   alt z={(c-b)/cse:+.2f}   {time.perf_counter()-t0:.0f}s")
