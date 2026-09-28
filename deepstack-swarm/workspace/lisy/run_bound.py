"""Driver: the real-deal lower bound for one spot, all seats, several attacker models.

    .venv/bin/python -u run_bound.py --spot pf3-10bb-icm --deals 20000000
    .venv/bin/python -u run_bound.py --spot tier1-n6-15bb --deals 3000000

At n = 3 the exact real-deal best response also exists (`cardbr.exact3_values(weight="joint")`)
and is printed next to the bound, so tightness is measured rather than assumed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE.parents[3]), str(HERE.parent / "burch" / "open3bet"),
          str(HERE.parent / "bowling" / "tier1chart")):
    sys.path.insert(0, p)

import adversary as adv  # noqa: E402
import cardbr  # noqa: E402
import seqbr  # noqa: E402
from pushfold import coach, floor, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

OUT = HERE / "bounds"
OUT.mkdir(exist_ok=True)
CACHE = HERE / "solved"
CACHE.mkdir(exist_ok=True)


def pushfold_spot(name: str):
    if name == "pf3-10bb-icm":
        return (Spot(stacks=(10.0,) * 3),
                icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,)), "ICM chips/hand")
    if name == "pf3-10bb-chip":
        return Spot(stacks=(10.0,) * 3), None, "bb/hand"
    if name == "pf2-10bb-icm":
        return (Spot(stacks=(10.0,) * 2),
                icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,)), "ICM chips/hand")
    if name == "pf6-15bb-icm":
        return (Spot(stacks=(15.0,) * 6),
                icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(15.0,) * 3), "ICM chips/hand")
    if name == "pf9-15bb-icm":
        return (Spot(stacks=(15.0,) * 9),
                icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(15.0,) * 4), "ICM chips/hand")
    raise SystemExit(f"unknown pushfold spot {name}")


def tier1_cell(name: str):
    """`tier1-nK-Sbb`: my own solve (solve_cells.py) of the shipped geometry (small/bubble/46)."""
    import floor3
    import scenarios as S
    body = name.split("-", 1)[1]
    n = int(body.split("-")[0][1:])
    stack = float(body.split("-")[1][:-2])
    path = HERE / "cells" / f"small-bubble-n{n}-{stack:g}bb-left46.npz"
    if not path.exists():
        raise SystemExit(f"{path} missing; run solve_cells.py {n} --stack={stack:g} first")
    sigma = np.load(path)["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * n), tier1=True)
    pay = S.payouts("small", n, 46, stack)
    return tree, pay, "ICM chips/hand", sigma


def pushfold_sigma(spot, pay, target, max_iters):
    key = f"pf-n{spot.n}-{spot.stacks[0]:g}bb-{'icm' if pay else 'chip'}-t{target:g}-i{max_iters}"
    path = CACHE / f"{key}.npz"
    if path.exists():
        return np.load(path)["sigma"], json.loads((CACHE / f"{key}.json").read_text())
    t0 = time.perf_counter()
    res = coach.solve(spot, payouts=pay, target=target, max_iters=max_iters)
    np.savez_compressed(path, sigma=res.strategy)
    meta = {"iterations": res.iterations, "model_exploitability": res.exploitability,
            "seconds": round(time.perf_counter() - t0, 1)}
    (CACHE / f"{key}.json").write_text(json.dumps(meta, indent=1))
    return res.strategy, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", default="pf3-10bb-icm")
    ap.add_argument("--deals", type=int, default=20_000_000)
    ap.add_argument("--seed", type=int, default=20260928)
    ap.add_argument("--chunk", type=int, default=250_000)
    ap.add_argument("--models", default="model,onebody,pairjoint")
    ap.add_argument("--target", type=float, default=0.0)
    ap.add_argument("--iters", type=int, default=3200)
    args = ap.parse_args()

    tier1 = args.spot.startswith("tier1-")
    t0 = time.perf_counter()
    if tier1:
        tree, pay, unit, sigma = tier1_cell(args.spot)
        import seqbr3
        game = seqbr3.from_floor3(tree)
        meta = {"source": "workspace/lisy/cells", "model_exploitability": None}
    else:
        spot, pay, unit = pushfold_spot(args.spot)
        sigma, meta = pushfold_sigma(spot, pay, args.target, args.iters)
        game = seqbr.from_floor(floor.build(spot))
    n = game.spot.n
    models = [m for m in args.models.split(",") if m]

    print(f"spot {args.spot}  n={n}  unit={unit}  deals={args.deals:,} seed={args.seed}  "
          f"game {len(game.nodes)} nodes, {len(game.endings)} endings", flush=True)
    print(f"  solve: {meta}", flush=True)

    print("  building attacker models ...", flush=True)
    Us, pols = {}, {}
    for m in models:
        a = time.perf_counter()
        Us[m] = adv.attacker_u(game, sigma, pay, m)
        pols[m] = {s: adv.br_policy(game, Us[m], s) for s in range(n)}
        print(f"    {m:<9} {time.perf_counter()-a:.1f}s", flush=True)

    rep_m = seqbr.audit(game, sigma, pay, U=Us["model"] if "model" in Us
                        else adv.attacker_u(game, sigma, pay, "model"))
    print(f"  model exploitability (auditor convention) {rep_m.gain.max():.6f} {unit}   "
          f"per seat {np.array2string(rep_m.gain, precision=6)}", flush=True)

    U_exact = rep_r = None
    if n == 3:
        U_exact = cardbr.exact3_values(game, sigma, pay, weight="joint")
        rep_r = seqbr.audit(game, sigma, pay, U=U_exact)
        print(f"  EXACT real (joint, n=3 only): max {rep_r.gain.max():.6f} {unit}   "
              f"per seat {np.array2string(rep_r.gain, precision=6)}", flush=True)

    results = {}
    for s in range(n):
        row = {}
        for m in models:
            a = time.perf_counter()
            r = adv.sim_gain(game, sigma, s, pols[m][s], args.deals, args.seed + 101 * s,
                             chunk=args.chunk, payouts=pay)
            r["seconds"] = round(time.perf_counter() - a, 1)
            r["attacker"] = m
            row[m] = r
            print(f"  seat {s}  {m:<9} gain {r['gain']:.6f} (se {r['se']:.1e})  "
                  f"ev {r['ev']:.6f}   {r['seconds']}s", flush=True)
        b, bi = adv.bound(list(row.values()))
        best = list(row.values())[bi]
        print(f"  seat {s}  ->  BOUND {b:.6f} ({unit})  from {best['attacker']} "
              f"gain {best['gain']:.6f}", flush=True)
        row["_bound"] = b
        row["_attacker"] = best["attacker"]
        results[f"seat{s}"] = row

    feas = [results[f"seat{s}"]["_bound"] for s in range(n)]
    print(f"\nREAL EXPLOITABILITY 95% LOWER BOUND (max over seats): {max(feas):.6f} {unit}",
          flush=True)
    if rep_r is not None:
        print(f"EXACT (n=3):                                          {rep_r.gain.max():.6f} {unit}",
              flush=True)
    tag = args.spot
    (OUT / f"{tag}-d{args.deals}.json").write_text(json.dumps(
        {"spot": args.spot, "n": n, "unit": unit, "deals": args.deals, "seed": args.seed,
         "chunk": args.chunk, "models": models, "solve": meta,
         "attacker_models": "workspace/lisy/adversary.py: ATTACKER_MODELS",
         "model_exploitability": float(rep_m.gain.max()),
         "model_per_seat": [float(x) for x in rep_m.gain],
         "exact_real": None if rep_r is None else [float(x) for x in rep_r.gain],
         "bound": float(max(feas)), "results": results}, indent=1, default=float))
    print(f"wrote {OUT / f'{tag}-d{args.deals}.json'}  ({time.perf_counter()-t0:.0f}s total)",
          flush=True)


if __name__ == "__main__":
    main()
