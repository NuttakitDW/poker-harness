"""Does the model-vs-real gap grow with the number of seats?

Player count held fixed at 9 (table n + 9-n in the field), stacks 15bb, ICM 50/30/20,
target given by --target. n=3 is the exact joint; n>=4 is MC over real deals (se from 4 batch seeds).

Run: .venv/bin/python deepstack-swarm/workspace/johanson/sweepN.py [--mc N] [--batches B]
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, seqbr, cardbr
from pushfold import coach, floor, icm
from pushfold.spot import Spot

ap = argparse.ArgumentParser()
ap.add_argument("--mc", type=int, default=400_000)
ap.add_argument("--batches", type=int, default=4)
ap.add_argument("--target", type=float, default=1e-4)
a = ap.parse_args()

print(f"9 players left, 3 paid (50/30/20). Table n = 3..9, field = 9-n. target={a.target:g}, MC {a.mc:,} x{a.batches}.")
print("  n   modelGain   realGain  gap(max)  gap(sum)  per-seat gaps (se)")
for n in range(3, 10):
    spot = Spot(stacks=(15.,) * n)
    pay = icm.Payouts(prizes=(50.,30.,20.), field=(15.,) * (9 - n))
    res = coach.solve(spot, payouts=pay, target=a.target, max_iters=20000)
    game = seqbr.from_floor(floor.build(spot))
    s = res.strategy
    mg = seqbr.audit(game, s, pay, U=cardbr.analytic_values(game, s, pay, kind="model")).gain
    if n == 3:
        rg = seqbr.audit(game, s, pay, U=cardbr.exact3_values(game, s, pay, weight="joint")).gain
        se = np.zeros(n)
    else:
        rows = []
        for b in range(a.batches):
            U, _ = cardbr.mc_values(game, s, pay, samples=a.mc, seed=3000 + b)
            rows.append(seqbr.audit(game, s, pay, U=U).gain)
        rows = np.array(rows); rg = rows.mean(axis=0)
        se = rows.std(axis=0, ddof=1) / np.sqrt(a.batches)
    g = rg - mg
    print(f" {n:>2}  {mg.max():>9.6f}  {rg.max():>9.6f}  {np.abs(g).max():>8.6f}  "
          f"{np.abs(g).sum():>8.6f}  " + " ".join(f"{v:+.4f}+-{e:.4f}" for v, e in zip(g, se)),
          flush=True)
