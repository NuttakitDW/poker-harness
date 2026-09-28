"""Solve my own copies of the Tier 1 grid cells I need, with bowling's own provenance record.

Same conventions as `tier1chart/grid.py` (`small` structure, bubble = 46 left, equal stacks
15bb, `floor3.build(tier1=True)`, cfr+, check_every 25, target 0.0006, `fasticm3.FastAuditor`)
and the same per-cell record, because `tier1chart/verify_cells.py` is the cell-record standard.
Written to `workspace/lisy/cells/`, NOT to the grid's `cells/` -- the grid is mid re-solve under
`fa654842` and a resumable driver must not see a second writer.

Usage: .venv/bin/python solve_cells.py [n ...]     (default 3 6 9)
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BOWLING = HERE.parent / "bowling" / "tier1chart"
OPEN3BET = HERE.parent / "burch" / "open3bet"
for p in (str(HERE), str(BOWLING), str(OPEN3BET), str(HERE.parents[2])):
    sys.path.insert(0, p)

import provenance as prov  # noqa: E402  (bowling's)
import scenarios as S  # noqa: E402

import floor3  # noqa: E402
import solve3  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

OUT = HERE / "cells"
OUT.mkdir(exist_ok=True)
TARGET = 0.0006
CHECK_EVERY = 25
SETTING = "small"
LEFT = 46


def one(n: int, stack: float) -> dict:
    key = f"{SETTING}-bubble-n{n}-{stack:g}bb-left{LEFT}"
    path = OUT / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    rec: dict = {"cell": key, "setting": SETTING, "stage": "bubble", "n": n, "stack": stack,
                 "left": LEFT, "target": TARGET, "check_every": CHECK_EVERY, "method": "cfr+",
                 "commit": "b75e315", "unit": "ICM chips/hand", "auditor": "fasticm3.FastAuditor",
                 "code_fingerprint": prov.fingerprint(), "code": prov.digests(),
                 "solver_dir": str(OPEN3BET), "written_by": "workspace/lisy/solve_cells.py"}
    try:
        tree = floor3.build(Spot(stacks=(stack,) * n), tier1=True)
        pay = S.payouts(SETTING, n, LEFT, stack)
        rec |= {"build": {"tier1": True}, "stacks": [stack] * n, "cap": tree.cap,
                "crowd": pay.crowd, "prizes_paid": len(pay.prizes), "nodes": len(tree.nodes),
                "terminals": len(tree.terminals), "counts": tree.counts()}
        print(f"{key:<30} {len(tree.nodes)} nodes, crowd {pay.crowd} ...", flush=True)
        sol = solve3.solve_icm(tree, pay, TARGET, "cfr+", check_every=CHECK_EVERY,
                               max_iters=20000)
        rec |= {"converged": sol.converged, "iters": sol.history[-1][0],
                "seconds": round(sol.seconds, 1), "final_gain": sol.history[-1][1],
                "history": [[it, g] for it, g in sol.history]}
        np.savez_compressed(OUT / f"{key}.npz", sigma=sol.st.average())
    except Exception as e:  # noqa: BLE001
        rec |= {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
    path.write_text(json.dumps(rec, indent=1))
    print(f"{key:<30} {'ERR' if 'error' in rec else ('ok ' if rec['converged'] else 'NO ')} "
          f"{rec.get('final_gain', float('nan')):.6f} {rec.get('iters', '-')} it "
          f"{rec.get('seconds', '-')}s {rec.get('error', '')}", flush=True)
    return rec


if __name__ == "__main__":
    ns = [int(a) for a in sys.argv[1:] if not a.startswith("--")] or [3, 6, 9]
    stack = 15.0
    for a in sys.argv[1:]:
        if a.startswith("--stack="):
            stack = float(a.split("=", 1)[1])
    t0 = time.perf_counter()
    for n in ns:
        one(n, stack)
    print(f"total {time.perf_counter()-t0:.0f}s")
