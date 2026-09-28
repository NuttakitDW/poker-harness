"""Per-seat model-vs-real gap: audit a chart priced by the Pricer's model, then re-price the
same chart under the real deal (cardbr). Reports the best-response gain and the EV, per seat.

Usage: .venv/bin/python deepstack-swarm/workspace/johanson/gap.py [--iters N] [--mc N]
"""
import argparse, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, seqbr, cardbr
from pushfold import coach, floor, icm
from pushfold.spot import Spot

ap = argparse.ArgumentParser()
ap.add_argument("--iters", type=int, default=400)
ap.add_argument("--mc", type=int, default=1_000_000)
ap.add_argument("--batches", type=int, default=8)
ap.add_argument("--target", type=float, default=0.01)
ap.add_argument("--only", default="")
args = ap.parse_args()

CASES = [
    ("3max 10bb chip",    Spot(stacks=(10.,)*3), None, "joint"),
    ("3max 10bb ICM",     Spot(stacks=(10.,)*3), icm.Payouts(prizes=(50.,30.,20.), field=(10.,)), "joint"),
    ("3max 12/10/8 ICM",  Spot(stacks=(12.,10.,8.)),
     icm.Payouts(prizes=(50.,30.,20.), field=(10.,)*3), "joint"),
    ("6max 15bb a1 ICM",  Spot(stacks=(15.,)*6, ante=1.0),
     icm.Payouts(prizes=(50.,30.,20.), field=(15.,)*3), "mc"),
    ("9max 15bb ICM",     Spot(stacks=(15.,)*9),
     icm.Payouts(prizes=(50.,30.,20.), field=(15.,)*4), "mc"),
]

def audits(game, sigma, payouts, U):
    r = seqbr.audit(game, sigma, payouts, U=U)
    return r

for label, spot, pay, kind in CASES:
    t0 = time.perf_counter()
    if args.only and args.only not in label: continue
    res = coach.solve(spot, payouts=pay, target=args.target, max_iters=args.iters)
    tree = floor.build(spot); game = seqbr.from_floor(tree)
    sigma = res.strategy
    U_model = cardbr.analytic_values(game, sigma, pay, kind="model")
    rep_m = audits(game, sigma, pay, U_model)
    if kind == "joint":
        U_real = cardbr.exact3_values(game, sigma, pay, weight="joint")
        rep_r = audits(game, sigma, pay, U_real)
        rows = [(rep_r.gain - rep_m.gain, rep_r.ev - rep_m.ev)]
        tag = f"exact joint, n={spot.n}"
    else:
        diffs_g, diffs_e = [], []
        for b in range(args.batches):
            U_real, cnt = cardbr.mc_values(game, sigma, pay, samples=args.mc,
                                           seed=1000 + b, uniform_hero=True)
            r = audits(game, sigma, pay, U_real)
            diffs_g.append(r.gain - rep_m.gain); diffs_e.append(r.ev - rep_m.ev)
        G = np.array(diffs_g); E = np.array(diffs_e)
        rows = [(G.mean(axis=0), E.mean(axis=0))]
        se_g = G.std(axis=0, ddof=1) / np.sqrt(args.batches)
        se_e = E.std(axis=0, ddof=1) / np.sqrt(args.batches)
        tag = f"MC {args.mc:,} x{args.batches} batches, n={spot.n}"
    dg, de = rows[0]
    print(f"\n{label}  ({tag})   solve {res.iterations} it, exploit(model) {res.exploitability:.5f}, "
          f"{time.perf_counter()-t0:.0f}s")
    print("  seat        modelGain    gainGap    modelEV     evGap")
    for s in range(spot.n):
        extra = ""
        if kind == "mc":
            extra = f"  +- {se_g[s]:.4f} / {se_e[s]:.4f}"
        print(f"  {s:>4}   {rep_m.gain[s]:>10.5f} {dg[s]:>10.5f} {rep_m.ev[s]:>10.5f} "
              f"{de[s]:>9.5f}{extra}")
    real = rep_m.gain + dg
    print(f"  |gain gap| max {np.abs(dg).max():.5f}   |ev gap| max {np.abs(de).max():.5f}")
    print(f"  exploitability max-seat: model {rep_m.gain.max():.5f}  real {real.max():.5f}"
          f"  (ratio {real.max()/max(rep_m.gain.max(),1e-12):.2f}x)")
