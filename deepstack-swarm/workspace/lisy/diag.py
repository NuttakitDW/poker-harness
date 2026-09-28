"""Variance / cost diagnostics for the simulator. Not a finding -- a measurement of the tool."""
from __future__ import annotations

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

spot = Spot(stacks=(10.0,) * 3)
pay = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,))
res = coach.solve(spot, payouts=pay, target=0.0, max_iters=3200)
game = seqbr.from_floor(floor.build(spot))
sigma = res.strategy
U_real = cardbr.exact3_values(game, sigma, pay, weight="joint")
pol = adv.br_policy(game, U_real, 0)

D = 400_000
t0 = time.perf_counter()
deals = adv.real_deals(3, D, seed=11)
rows = adv.payoff_rows(game, 0, deals, payouts=pay)
base = adv.profile_ev(game, rows, deals, sigma)
alt = adv.profile_ev(game, rows, deals, sigma, 0, pol)
dt = time.perf_counter() - t0
d = alt - base
print(f"{D:,} deals in {dt:.1f}s ({dt/D*1e6:.1f} us/deal, payoff_rows+2 walks)")
print(f"  sd(base)={base.std():.4f}  sd(alt)={alt.std():.4f}  sd(diff)={d.std():.4f}")
print(f"  corr(base,alt)={np.corrcoef(base,alt)[0,1]:.4f}   mean diff={d.mean():.6f} "
      f"se={d.std()/np.sqrt(D):.2e}")
# how much of the variance is between hero classes?
hero = deals[:, 0]
m = np.array([0.0] * 169)
big = np.zeros(169)
for h in range(169):
    sel = hero == h
    if sel.sum():
        big[h] = d[sel].mean()
        m[h] = sel.sum()
w = m / m.sum()
between = float(w @ (big - d.mean()) ** 2)
print(f"  var(diff)={d.var():.4f}  between-hero-class var={between:.4f} "
      f"({100*between/d.var():.1f}%)")
print(f"  classes where BR != argmax(sigma): "
      f"{int(sum((pol[i]>=0).sum() > 0 for i in range(len(game.nodes))))} nodes")
