"""First Tier 1 ICM chart: grid driver.

Tier 1 = open-or-jam (no flat, no 3bet), so every ending is a fold, an uncontested raise or an
all-in showdown -- exactly the three types pushfold/ already prices. No flop is ever seen.
See workspace/bowling/open3bet-design.md Sec 6b.

One cell = (setting, n seats, stack bb, players left). Solved to target = 0.0006 ICM chips/hand
(the lifetime-of-play eps for the bubble spot, davis-lifetime-eps.md, adopted in
open3bet-design.md Sec 12). Resumable: each cell is written as its own json + npz.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
import scenarios as S  # noqa: E402
import provenance as prov  # noqa: E402

from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402
import solve3  # noqa: E402

OUT = HERE / "cells"
OUT.mkdir(exist_ok=True)
TARGET = 0.0006      # the lifetime eps at the bubble; see target_for below
# johanson, `johanson-model-vs-real-gap.md` (2026-09-28): the model's OWN per-seat error in the
# best-response gain, model vs real deal, in ICM chips/hand. It GROWS with seat count.
MODEL_FIDELITY = {3: 0.0055, 6: 0.0075, 9: 0.0119}
# davis, `davis-grid-sigma.md` Sec 2: the lifetime eps of a heads-up cell, in ICM chips/hand, by
# stack. Heads-up pricing is exact, so the model error is ~0 and the lifetime bar is the binding
# one. Conservative: the minimum over structures at each stack, since davis measures `past` eps
# ABOVE `bubble` (x1.11-1.50), so using the bubble value everywhere over-solves `past` harmlessly.
EPS_N2 = {8.0: 0.00059, 12.0: 0.00071, 15.0: 0.00077, 20.0: 0.00082, 30.0: 0.00099}

# Passed to floor3.build for every cell. Recorded per cell because a file hash cannot tell
# `tier1=True, behind_cap=None` from `tier1=True, behind_cap=1` -- both live in floor3.py (burch).
BUILD = {"tier1": True}


CHECK_EVERY = 25


def target_for(n: int, stack: float) -> float:
    """Stop when the solver is as converged as the model is accurate, or at the lifetime eps.

        target(n) = min(lifetime eps, model fidelity at n seats)

    This is the "floor vs ceiling" rule of open3bet-design.md Sec 11 applied per seat count. At 2
    seats the model is exact enough that the lifetime eps 0.0006 is the binding bar. At 3+ seats
    johanson's exact joint measures the model's OWN error at 5.5e-3 ICM chips/hand (n=3, 2026-09-28)
    -- ~9x the lifetime eps -- so solving to 0.0006 refines the wrong thing: the solve converges,
    the chart does not get more correct, and it costs ~14 min/cell at n=6 and 30+ at n=9 against
    seconds at n=2.

    Using the measured fidelity itself (0.0055) rather than an invented margin: at n>=3 the solver
    error and the model error are then the same size, which is the point of the rule. A margin would
    be a second guess on top of a measurement.

    NOTE this changes no claim. At n>=3 the chart already says "solved to a stop rule in a model
    whose real figure is ~10-40x larger"; 0.002 vs 0.0055 is invisible under that sentence. Cells
    already solved at 0.002 are *tighter* than this and were kept rather than re-solved.

    Residual risk: 5.5e-3 is one spot at one seat count. If card-removal error *shrinks* with seats,
    this is too loose at n=6/n=9. The expected direction is that it grows (more independently dealt
    opponents), which is why a single value is used for all n>=3; lisy's bound tests it.
    """
    return EPS_N2[stack] if n == 2 else MODEL_FIDELITY[n]


def auditor(n: int) -> str:
    """`fasticm3.FastAuditor` (burch, `verify_fasticm3.py`): a check costs ~1 iteration at every
    n, so `check_every` goes back to Burch thesis Sec 3.3.1's "check every few, not every step".
    Before it existed a check cost 313 iterations at n=6 and 537 at n=9 (probe2.py); a first set
    of cells was solved at check_every=200 on that slow auditor and has been quarantined to
    `cells-prev-noprov/` (see findings/bowling-grid-provenance.md)."""
    del n
    return "fasticm3.FastAuditor"


def one(setting: str, n: int, stack: float, left: int, label: str) -> dict:
    key = f"{setting}-{label}-n{n}-{stack:g}bb-left{left}"
    path = OUT / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    ce = CHECK_EVERY
    target = target_for(n, stack)
    rec: dict = {"cell": key, "setting": setting, "stage": label, "n": n, "stack": stack,
                 "left": left, "target": target, "lifetime_eps": TARGET, "check_every": ce,
                 "method": "cfr+",
                 "commit": "b75e315", "unit": "ICM chips/hand", "auditor": auditor(n),
                 # `commit` pins pushfold/ and the repo. It does NOT pin the solver:
                 # deepstack-swarm/workspace/ is untracked by git. These two fields do.
                 "code_fingerprint": prov.fingerprint(), "code": prov.digests()}
    try:
        tree = floor3.build(Spot(stacks=(stack,) * n), **BUILD)
        pay = S.payouts(setting, n, left, stack)
        rec |= {"build": dict(BUILD), "stacks": [stack] * n, "cap": tree.cap,
                "crowd": pay.crowd, "prizes_paid": len(pay.prizes), "nodes": len(tree.nodes),
                "terminals": len(tree.terminals), "counts": tree.counts()}
        print(f"{key:<34} solving ({len(tree.nodes)} nodes, crowd {pay.crowd}) ...", flush=True)
        sol = solve3.solve_icm(tree, pay, target, "cfr+", check_every=ce, max_iters=20000)
        rec |= {"converged": sol.converged, "iters": sol.history[-1][0],
                "seconds": round(sol.seconds, 1), "final_gain": sol.history[-1][1],
                "history": [[it, g] for it, g in sol.history]}
        np.savez_compressed(OUT / f"{key}.npz", sigma=sol.st.average())
    except Exception as e:  # noqa: BLE001
        rec |= {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
    path.write_text(json.dumps(rec, indent=1))
    print(f"{key:<34} {'ERR' if 'error' in rec else ('ok ' if rec['converged'] else 'NO ')} "
          f"{rec.get('final_gain', float('nan')):.6f} {rec.get('iters', '-')} it "
          f"{rec.get('seconds', '-')}s {rec.get('error', '')}", flush=True)
    return rec


def main() -> None:
    fp = prov.fingerprint()
    dest = prov.snapshot()
    stacks = (8.0, 12.0, 15.0, 20.0, 30.0)
    plan = [(s, lab, left, n, st) for s in ("small", "big")
            for lab, left in S.stages(s)[:2] for n in (2, 3, 6, 9) for st in stacks]
    (OUT / "RUN.json").write_text(json.dumps(
        {"code_fingerprint": fp, "code": prov.digests(), "build": BUILD,
         "lifetime_eps": TARGET, "model_fidelity": MODEL_FIDELITY, "eps_n2": EPS_N2,
         "check_every": CHECK_EVERY, "method": "cfr+", "max_iters": 20000,
         "auditor": auditor(6), "commit": "b75e315",
         "plan": [f"{s}-{lab}-n{n}-{st:g}bb-left{left}" for s, lab, left, n, st in plan]},
        indent=1))
    print(f"code fingerprint {fp}  snapshot -> {dest}  {len(plan)} cells planned", flush=True)
    stale = []
    for setting, label, left, n, stack in plan:
        rec = one(setting, n, stack, left, label)
        if rec.get("code_fingerprint") != fp:
            stale.append(rec["cell"])
    if stale:
        print(f"WARNING: {len(stale)} cells carry a different fingerprint than this run "
              f"({fp}); they are not the same artifact: {stale}", flush=True)


if __name__ == "__main__":
    main()
