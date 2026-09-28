"""Seed sweep of the Monte Carlo 3-way tables on the 6-handed 15bb Tier 1 spot.

Game: Tier 1 (open-or-jam), n = 6, equal 15bb stacks, sb 0.5 / bb 1, no ante, fee 0, cap 3.
ICM: 50/30/20, field = () (6 players at the table; `burch-icm-pricer3.md` pads the field to 4
only when n < 4). Chip EV on the same spot.

  .venv/bin/python noise.py solve A|B|C     # 2000 CFR+ iterations, audits every 200, save profile
  .venv/bin/python noise.py cross           # re-audit every saved profile under every saved table

The split exists so solves can run while the tables are still being built. `cross` is the
measurement that matters: a *fixed* strategy audited under a different seed's tables isolates
evaluation noise from any change in the solved profile.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from tableswap import install_seed, seed_paths  # noqa: E402

from pushfold import icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import coach3  # noqa: E402
import floor3  # noqa: E402
import icm_pricer3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402

N_SEATS = 6
STACK = 15.0
ITERS = 2000
CHECK = 200
METHOD = "cfr+"
BOTH = ("chip", "icm")


def tree_and_payouts():
    tree = floor3.build(Spot(stacks=(STACK,) * N_SEATS), tier1=True)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=())
    payouts.check(N_SEATS)
    return tree, payouts


def fresh(tree, payouts, mode):
    """(state, auditor) for `mode`, built against whatever tables are installed now."""
    if mode == "chip":
        plan = pricer3.plan(tree)
        return coach3.start(tree, plan), seqbr3.FastAuditor(seqbr3.from_floor3(tree), plan)
    plan = icm_pricer3.plan(tree, payouts)
    return coach3.start(tree, plan), seqbr3.Auditor(seqbr3.from_floor3(tree), payouts)


def solve(name: str) -> None:
    tree, payouts = tree_and_payouts()
    print(f"n={N_SEATS} stack={STACK} tier1: {len(tree.nodes)} nodes, "
          f"{len(tree.terminals)} terminals {tree.counts()}", flush=True)
    install_seed(name)
    out, hist = {}, {}
    for mode in BOTH:
        st, aud = fresh(tree, payouts, mode)
        h, t0 = [], time.perf_counter()
        for it in range(1, ITERS + 1):
            coach3.iterate(st, METHOD)
            if it % CHECK == 0:
                h.append((it, float(aud.audit(st.average()).exploitability)))
        hist[mode] = h
        out[mode] = st.average()
        unit = "bb/hand" if mode == "chip" else "ICM chips/hand"
        print(f"[{name}] {mode} {time.perf_counter()-t0:6.1f}s  "
              f"{h[-1][1]:.6f} {unit} @ {ITERS}  trail {[round(v,6) for _,v in h]}", flush=True)
    np.savez_compressed(HERE / f"solve-{name}.npz",
                        meta=json.dumps({"hist": hist, "seed": name, "n": N_SEATS,
                                         "stack": STACK, "iters": ITERS, "check": CHECK}),
                        **{f"{m}_{name}": out[m] for m in BOTH})


def cross() -> None:
    tree, payouts = tree_and_payouts()
    files = sorted(HERE.glob("solve-*.npz"))
    loaded = {f.stem.split("-")[1]: np.load(f, allow_pickle=False) for f in files}
    seeds = sorted(loaded)
    print("cross-auditing seeds", seeds, flush=True)
    crossn, hist = {}, {}
    for name in seeds:
        hist[name] = json.loads(str(loaded[name]["meta"]))["hist"]
    for audit_seed in seeds:
        install_seed(audit_seed)
        for mode in BOTH:
            st, aud = fresh(tree, payouts, mode)      # tables are all that differ
            for solve_seed in seeds:
                sigma = loaded[solve_seed][f"{mode}_{solve_seed}"]
                t0 = time.perf_counter()
                crossn[f"{mode}|{solve_seed}|{audit_seed}"] = float(aud.audit(sigma).exploitability)
                print(f"  {mode} {solve_seed}->{audit_seed} "
                      f"{crossn[f'{mode}|{solve_seed}|{audit_seed}']:.6f} "
                      f"({time.perf_counter()-t0:.1f}s)", flush=True)
    np.savez_compressed(HERE / "noise.npz",
                        meta=json.dumps({"cross": crossn, "hist": hist, "seeds": seeds,
                                         "n": N_SEATS, "stack": STACK,
                                         "iters": ITERS, "check": CHECK}))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "cross":
        cross()
    else:
        for s in sys.argv[2:]:
            solve(s)
