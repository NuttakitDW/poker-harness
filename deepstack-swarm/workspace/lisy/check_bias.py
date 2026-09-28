"""Is the simulator unbiased? Seat 0 of the n=3 push/fold spot, exact real BR as attacker.

The exact real best-response gain there is 0.005476 (johanson, exact joint). If the attacker
policy `br_policy(U_exact_joint, 0)` and the simulator are both right, the running mean must
converge to that number. Small-sample runs landed ~0.9 se below it, which is why this exists.

Usage: .venv/bin/python check_bias.py [--deals 200000000]
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
from pushfold import floor, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--deals", type=int, default=200_000_000)
ap.add_argument("--chunk", type=int, default=1_000_000)
ap.add_argument("--seed", type=int, default=555)
args = ap.parse_args()

spot = Spot(stacks=(10.0,) * 3)
pay = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,))
game = seqbr.from_floor(floor.build(spot))
sigma = np.load(HERE / "solved" /
                "pf-n3-10bb-icm-t0-i3200.npz")["sigma"]
U_exact = cardbr.exact3_values(game, sigma, pay, weight="joint")
rep = seqbr.audit(game, sigma, pay, U=U_exact)
pol = adv.br_policy(game, U_exact, 0)
print(f"exact real BR gain, seat 0: {rep.gain[0]:.6f}  (audit), seat max {rep.gain.max():.6f}")

gc: list[tuple[int, float, float]] = []
ec: list[tuple[int, float, float]] = []
t0 = time.perf_counter()
for deals in adv.deal_chunks(3, args.deals, seed=args.seed, chunk=args.chunk):
    base = adv.profile_ev(game, deals, sigma, 0, payouts=pay)
    alt = adv.profile_ev(game, deals, sigma, 0, 0, pol, payouts=pay)
    d = alt - base
    gc.append((len(d), float(d.mean()), float(d.var(ddof=1))))
    ec.append((len(base), float(base.mean()), float(base.var(ddof=1))))
    m, se = adv._pooled(gc)
    if len(gc) % 10 == 0:
        e, ese = adv._pooled(ec)
        print(f"  {sum(c[0] for c in gc)/1e6:>7.0f}M  gain {m:.6f} (se {se:.1e})  "
              f"z={((m - rep.gain[0])/se if se else 0):+.2f}   ev {e:.6f} ({ese:.1e})  "
              f"{time.perf_counter()-t0:.0f}s", flush=True)
g, gse = adv._pooled(gc)
e, ese = adv._pooled(ec)
print(f"\nfinal: gain {g:.6f} (se {gse:.1e})  vs exact {rep.gain[0]:.6f}  "
      f"z={(g-rep.gain[0])/gse:+.2f}")
print(f"       ev   {e:.6f} (se {ese:.1e})  vs exact {rep.ev[0]:.6f}  z={(e-rep.ev[0])/ese:+.2f}")
