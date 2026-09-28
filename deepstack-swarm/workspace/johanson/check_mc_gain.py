"""At n=3 the joint is exact; MC must reproduce the same best-response GAIN. That is the check
the n>=4 (MC-only) numbers rest on."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, seqbr, cardbr
from pushfold import coach, floor, icm
from pushfold.spot import Spot

for label, spot, pay in [("3max chip", Spot(stacks=(10.,)*3), None),
                         ("3max ICM", Spot(stacks=(10.,)*3),
                          icm.Payouts(prizes=(50.,30.,20.), field=(10.,)))]:
    res = coach.solve(spot, payouts=pay, target=1e-4, max_iters=3000)
    game = seqbr.from_floor(floor.build(spot)); s = res.strategy
    p = None if pay is None else (50.,30.,20.,(10.,))
    Uj = cardbr.exact3_values(game, s, pay, weight="joint")
    rj = seqbr.audit(game, s, pay, U=Uj)
    gs, es = [], []
    for b in range(6):
        Um, cnt = cardbr.mc_values(game, s, pay, samples=2_000_000, seed=500+b)
        r = seqbr.audit(game, s, pay, U=Um)
        gs.append(r.gain); es.append(r.ev)
    G, E = np.array(gs), np.array(es)
    print(f"\n{label}: exact3 gain {rj.gain.round(6)}")
    print(f"          MC  gain {G.mean(axis=0).round(6)}  +- {G.std(axis=0,ddof=1).round(6)}")
    print(f"          diff     {(G.mean(axis=0)-rj.gain).round(6)}   "
          f"MC-own se {G.std(axis=0,ddof=1).round(6)}")
    print(f"          EV diff  {(E.mean(axis=0)-rj.ev).round(6)}   "
          f"MC-own se {E.std(axis=0,ddof=1).round(6)}")
