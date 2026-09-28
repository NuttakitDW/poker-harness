"""Model vs real exploitability as the solver runs: does the model number keep falling while
the real one stops? (The IJCAI 2011 'overfitting' check, at n = 3 where the real deal is exact.)

Run: .venv/bin/python deepstack-swarm/workspace/johanson/curve3.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, seqbr, cardbr
from pushfold import coach, floor, icm
from pushfold.spot import Spot

CASES = [
    ("3max 10bb chip",  Spot(stacks=(10.,)*3), None),
    ("3max 10bb ICM",   Spot(stacks=(10.,)*3), icm.Payouts(prizes=(50.,30.,20.), field=(10.,))),
]
STEPS = [10, 25, 50, 100, 200, 400, 800, 1600, 3200]

for label, spot, pay in CASES:
    tree = floor.build(spot); game = seqbr.from_floor(tree)
    print(f"\n{label}   n=3, exact joint. Exploitability = max over seats of the BR gain "
          f"(ICM chips/hand or bb/hand).")
    print("  iters     model      real     ratio   seat-gaps (real - model)")
    for it in STEPS:
        res = coach.solve(spot, payouts=pay, target=0.0, max_iters=it, check_every=10**9)
        s = res.strategy
        U_m = cardbr.analytic_values(game, s, pay, kind="model")
        U_r = cardbr.exact3_values(game, s, pay, weight="joint")
        rm, rr = seqbr.audit(game, s, pay, U=U_m), seqbr.audit(game, s, pay, U=U_r)
        g = rr.gain - rm.gain
        print(f"  {it:>5}  {rm.gain.max():.6f}  {rr.gain.max():.6f}  {rr.gain.max()/max(rm.gain.max(),1e-12):>6.1f}x"
              f"   " + " ".join(f"{v:+.4f}" for v in g))
