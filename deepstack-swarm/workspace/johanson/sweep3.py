"""n=3 sweeps, exact joint. Answers: (A) what is the ratio's denominator, (B) does the gap move
with stack depth, (C) does it move with the tournament stage (how far past the bubble).

Run: .venv/bin/python deepstack-swarm/workspace/johanson/sweep3.py [A|B|C|all]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, seqbr, cardbr
from pushfold import coach, floor, icm
from pushfold.spot import Spot

which = sys.argv[1] if len(sys.argv) > 1 else "all"
TARGET = float(sys.argv[2]) if len(sys.argv) > 2 else 1e-4
print(f"stop rule target={TARGET:g}")

def measure(spot, pay, target, iters):
    res = coach.solve(spot, payouts=pay, target=target, max_iters=iters)
    game = seqbr.from_floor(floor.build(spot))
    s = res.strategy
    rm = seqbr.audit(game, s, pay, U=cardbr.analytic_values(game, s, pay, kind="model"))
    rr = seqbr.audit(game, s, pay, U=cardbr.exact3_values(game, s, pay, weight="joint"))
    return res.iterations, rm.gain, rr.gain

if which in ("A", "all"):
    print("A. the ratio's denominator. 3max, target=0 (never stops early).")
    print("   iters        model(exploit, full precision)      real(exploit)         ratio")
    for label, pay in [("chip", None),
                       ("ICM", icm.Payouts(prizes=(50.,30.,20.), field=(10.,)))]:
        spot = Spot(stacks=(10.,)*3)
        for it in (400, 1600, 3200, 6400):
            n_it, mg, rg = measure(spot, pay, 0.0, it)
            m, r = mg.max(), rg.max()
            print(f"   {label:<4} {n_it:>5}  {m:.12e}  {r:.12e}  {r/m:>12.1f}x")
    print(f"   at stop rule target={TARGET:g}:")
    for label, pay in [("chip", None),
                       ("ICM", icm.Payouts(prizes=(50.,30.,20.), field=(10.,)))]:
        n_it, mg, rg = measure(Spot(stacks=(10.,)*3), pay, TARGET, 20000)
        print(f"   {label:<4} {n_it:>5}  {mg.max():.12e}  {rg.max():.12e}  {rg.max()/mg.max():>12.1f}x")

if which in ("B", "all"):
    print(f"\nB. stack depth, n=3 ICM (50/30/20, field (10,)*3), target={TARGET:g}.")
    print("   stacks        modelGain   realGain   gap(max seat)  per-seat gaps")
    for d in (8., 10., 12., 15., 20., 30.):
        pay = icm.Payouts(prizes=(50.,30.,20.), field=(10.,)*3)
        n_it, mg, rg = measure(Spot(stacks=(d,)*3), pay, TARGET, 20000)
        g = rg - mg
        print(f"   {d:>4.0f}bb   {mg.max():>10.6f}  {rg.max():>9.6f}   {np.abs(g).max():>10.6f}"
              f"   " + " ".join(f"{v:+.4f}" for v in g))
    print("   asymmetric 12/10/8 and 20/10/5:")
    for st in ((12.,10.,8.), (20.,10.,5.)):
        pay = icm.Payouts(prizes=(50.,30.,20.), field=(10.,)*3)
        n_it, mg, rg = measure(Spot(stacks=st), pay, TARGET, 20000)
        g = rg - mg
        print(f"   {str(st):<14} {mg.max():>10.6f}  {rg.max():>9.6f}   {np.abs(g).max():>10.6f}"
              f"   " + " ".join(f"{v:+.4f}" for v in g))

if which in ("C", "all"):
    print(f"\nC. stage, n=3 ICM 10bb stacks (50/30/20), target={TARGET:g}. field size = players at")
    print("   other tables; 0 = everybody left is paid.")
    print("   field        players  modelGain   realGain   gap(max seat)  per-seat gaps")
    for f in (0, 1, 2, 3, 6, 9):
        pay = icm.Payouts(prizes=(50.,30.,20.), field=(10.,)*f)
        n_it, mg, rg = measure(Spot(stacks=(10.,)*3), pay, TARGET, 20000)
        g = rg - mg
        print(f"   {f:>5}        {3+f:>3}   {mg.max():>10.6f}  {rg.max():>9.6f}   {np.abs(g).max():>10.6f}"
              f"   " + " ".join(f"{v:+.4f}" for v in g))
