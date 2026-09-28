"""Regression for `cardbr.py`. Exits nonzero on failure, so a silent break cannot land.

Three tests, each pinning down a different thing:
  T1 |model - seqbr|              the factored model path against the reference implementation
                                  (`seqbr.chip_values` / `seqbr.icm_values`).
  T2 |independent - seqbr|        the *same* deal through the both-opponents-on-axes code path
                                  that `exact3_values` uses for the exact joint. T1 exercises
                                  the factored path, T2 the tensor path; together they cover
                                  every line the joint path runs. Only the deal tensor `D`
                                  differs between "independent" and "joint", and `deal.joint2()`
                                  is checked separately by `check_deal.py` (marginals must be M).
  T3 |1body-analytic - 1body-exact3|  two independent implementations of the onebody deal.

Tolerance: `eq3`/`pw` are float32, so a 3-way chip-EV sum lands near 1e-8; ICM (float64 worth
differences) near 1e-14. The threshold 1e-6 sits well above the first and far below any real
break. Also prints the joint-vs-model gap, which is informational, not a test.

Run: .venv/bin/python deepstack-swarm/workspace/johanson/check_cardbr.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import cardbr
import seqbr
from pushfold import floor, icm
from pushfold.spot import Spot

N = 169
TOL = 1e-6
rng = np.random.default_rng(3)
CASES = [
    ("2max 10bb chip", Spot(stacks=(10.,) * 2), None),
    ("2max 10bb ICM", Spot(stacks=(10.,) * 2), icm.Payouts(prizes=(50., 30.), field=(10.,) * 2)),
    ("3max 10bb chip", Spot(stacks=(10.,) * 3), None),
    ("3max 10bb ICM", Spot(stacks=(10.,) * 3), icm.Payouts(prizes=(50., 30., 20.), field=(10.,))),
    ("4max 10bb ICM", Spot(stacks=(10.,) * 4), icm.Payouts(prizes=(50., 30., 20.), field=(10.,))),
    ("6max 15bb a1 ICM", Spot(stacks=(15.,) * 6, ante=1.0),
     icm.Payouts(prizes=(50., 30., 20.), field=(15.,) * 3)),
    ("9max 15bb ICM", Spot(stacks=(15.,) * 9), icm.Payouts(prizes=(50., 30., 20.), field=(15.,) * 4)),
]

worst = {1: 0.0, 2: 0.0, 3: 0.0}
fail = []
for label, spot, payouts in CASES:
    tree = floor.build(spot)
    game = seqbr.from_floor(tree)
    trials = 2 if spot.n <= 3 else 1
    for trial in range(trials):
        r = rng.random((len(tree.nodes), N, 1))
        sigma = np.concatenate([1 - r, r], axis=2)
        ref = seqbr.values(game, sigma, payouts)
        t1 = np.abs(cardbr.analytic_values(game, sigma, payouts, kind="model") - ref).max()
        msg = f"{label:<19} t{trial}  T1 |model-seqbr| {t1:.3e}"
        worst[1] = max(worst[1], t1)
        if t1 > TOL:
            fail.append(f"T1 {label} t{trial}: {t1:.3e} > {TOL:g}")
        if spot.n == 3:
            ind = cardbr.exact3_values(game, sigma, payouts, weight="independent")
            t2 = np.abs(ind - ref).max()
            ob = cardbr.exact3_values(game, sigma, payouts, weight="onebody")
            ob2 = cardbr.analytic_values(game, sigma, payouts, kind="onebody")
            t3 = np.abs(ob2 - ob).max()
            jt = cardbr.exact3_values(game, sigma, payouts, weight="joint")
            worst[2], worst[3] = max(worst[2], t2), max(worst[3], t3)
            msg += (f"  T2 |ind-seqbr| {t2:.3e}  T3 |1body x2| {t3:.3e}"
                    f"  [info] joint-vs-model max {np.abs(jt - ref).max():.3e}"
                    f" ev-rms {np.sqrt(((jt - ref) ** 2).mean()):.3e}")
            if t2 > TOL:
                fail.append(f"T2 {label} t{trial}: {t2:.3e} > {TOL:g}")
            if t3 > TOL:
                fail.append(f"T3 {label} t{trial}: {t3:.3e} > {TOL:g}")
        print(msg, flush=True)

print(f"\nworst T1 {worst[1]:.3e}   T2 {worst[2]:.3e}   T3 {worst[3]:.3e}   tolerance {TOL:g}")
if fail:
    print("FAIL")
    for line in fail:
        print("  " + line)
    sys.exit(1)
print("PASS: analytic_values(kind='model') reproduces seqbr.values; exact joint machinery checked")
