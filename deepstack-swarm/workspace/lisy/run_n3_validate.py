"""Validation of the LBR-style lower bound at n = 3, against johanson's exact joint.

Spot: push/fold, 3 seats, 10bb each, ICM 50/30/20 field (10,) -- exactly the spot in
findings/johanson-model-vs-real-gap.md Result 2, where the exact real-deal best-response
gain is 0.005476 ICM chips/hand while the model says ~3e-6.

Three things are checked here:
  1. `cardbr.exact3_values(weight="joint")` reproduces `seqbr.audit`'s real gain (johanson's
     number, recomputed).
  2. The exact real best response, *evaluated by the new simulator* (adversary.sim_gain),
     reproduces the same number. Different route, same value -> the simulator is right.
  3. The real EV of the chart itself matches, per seat.

Usage: .venv/bin/python run_n3_validate.py [--iters N] [--target X] [--deals N] [--seeds K]
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
ap.add_argument("--iters", type=int, default=3200)
ap.add_argument("--target", type=float, default=0.0)
ap.add_argument("--deals", type=int, default=2_000_000)
ap.add_argument("--seeds", type=int, default=3)
args = ap.parse_args()

spot = Spot(stacks=(10.0,) * 3)
pay = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,))
t0 = time.perf_counter()
res = coach.solve(spot, payouts=pay, target=args.target, max_iters=args.iters)
tree = floor.build(spot)
game = seqbr.from_floor(tree)
sigma = res.strategy
print(f"solved {res.iterations} iters, {time.perf_counter()-t0:.0f}s, "
      f"model exploitability {res.exploitability:.3e} ICM chips/hand")

U_model = cardbr.analytic_values(game, sigma, pay, kind="model")
rep_m = seqbr.audit(game, sigma, pay, U=U_model)
U_real = cardbr.exact3_values(game, sigma, pay, weight="joint")
rep_r = seqbr.audit(game, sigma, pay, U=U_real)
print(f"\nexact joint (johanson path): model gain max {rep_m.gain.max():.3e}  "
      f"real gain max {rep_r.gain.max():.6f}  ratio {rep_r.gain.max()/max(rep_m.gain.max(),1e-12):.0f}x")
print("  seat   modelEV     realEV    modelGain   realGain")
for s in range(3):
    print(f"  {s:>4}  {rep_m.ev[s]:>9.6f} {rep_r.ev[s]:>9.6f}  {rep_m.gain[s]:>10.3e} "
          f"{rep_r.gain[s]:>10.6f}")

print(f"\nsimulator check: {args.deals:,} real deals x {args.seeds} seeds, "
      "exact real BR evaluated by the new simulator")
print("  seat    audit realEV    sim realEV (sd)      audit realGain   sim gain (se)")
gains = []
for s in range(3):
    pol = adv.br_policy(game, U_real, s)
    evs, gs = [], []
    for k in range(args.seeds):
        deals = adv.real_deals(3, args.deals, seed=7000 + 991 * k)
        rows = adv.payoff_rows(game, s, deals, payouts=pay)
        evs.append(float(adv.profile_ev(game, rows, deals, sigma).mean()))
        base = adv.profile_ev(game, rows, deals, sigma)
        alt = adv.profile_ev(game, rows, deals, sigma, s, pol)
        d = alt - base
        gs.append((float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d)))))
    evs = np.array(evs)
    gm = float(np.mean([g for g, _ in gs]))
    gse = float(np.sqrt(np.mean([se ** 2 for _, se in gs]) / args.seeds))
    gains.append((gm, gse))
    print(f"  {s:>4}  {rep_r.ev[s]:>11.6f} {evs.mean():>11.6f} ({evs.std(ddof=1):.1e})  "
          f"{rep_r.gain[s]:>13.6f}  {gm:.6f} ({gse:.1e})")

bound = max(g - 1.96 * se for g, se in gains)
print(f"\nreal exploitability, auditor convention (max over seats): {max(g for g,_ in gains):.6f}")
print(f"95% one-sided lower bound: {bound:.6f}")
