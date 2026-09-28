"""Tier 1.5 ICM grid: the same cells as `grid.py` but with the 3bet.

`grid.py` is frozen (`fingerprint c371df3b`, 80 cells, Tier 1). This is the *other game*: the same
driver, `floor3.build(..., tier15=True)`, writing to its own `cells15/` so the two artifacts cannot
be mixed. Cost and the leaf-free check: `findings/bowling-tier1.5-icm-cost.md`.

**Default plan is the 20bb and 30bb rows only.** burch measured the 3bet as worth 0.0002 bb/hand at
15bb (below the lifetime bar, so a 15bb Tier 1.5 chart is the same chart) and 0.041 at 30bb (41x the
bar, so a Tier 1 30bb chart is not a 30bb chart). Below 20bb the extra action does not pay for
itself; shipping one grid is better than shipping two that differ by less than the model's error.

    # the recommended build (2 structures x 2 stages x 4 tables x 2 stacks = 32 cells)
    PYTHONPATH=. .venv/bin/python grid15.py
    # the full grid, all five stacks (80 cells, ~10-25x a Tier 1 cell each)
    PYTHONPATH=. .venv/bin/python grid15.py --all
    # one row
    PYTHONPATH=. .venv/bin/python grid15.py --stacks 15 30

Resumable: `one()` returns the existing record if `cells15/<key>.json` is present.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import grid  # noqa: E402  the Tier 1 driver: target_for, auditor, the key format
import provenance as prov  # noqa: E402
import scenarios as S  # noqa: E402
import traceback  # noqa: E402

from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402
import solve3  # noqa: E402

OUT = HERE / "cells15"
OUT.mkdir(exist_ok=True)
BUILD15 = {"tier15": True}
DEFAULT_STACKS = (20.0, 30.0)
ALL_STACKS = (8.0, 12.0, 15.0, 20.0, 30.0)


def one(setting: str, n: int, stack: float, left: int, label: str) -> dict:
    key = f"{setting}-{label}-n{n}-{stack:g}bb-left{left}"
    path = OUT / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    target = grid.target_for(n, stack)
    rec: dict = {"cell": key, "setting": setting, "stage": label, "n": n, "stack": stack,
                 "left": left, "target": target, "lifetime_eps": grid.TARGET,
                 "check_every": grid.CHECK_EVERY, "method": "cfr+",
                 "commit": "b75e315", "unit": "ICM chips/hand", "auditor": grid.auditor(n),
                 "tier": "1.5",
                 "code_fingerprint": prov.fingerprint(), "code": prov.digests()}
    try:
        tree = floor3.build(Spot(stacks=(stack,) * n), **BUILD15)
        pay = S.payouts(setting, n, left, stack)
        rec |= {"build": dict(BUILD15), "stacks": [stack] * n, "cap": tree.cap,
                "crowd": pay.crowd, "prizes_paid": len(pay.prizes), "nodes": len(tree.nodes),
                "terminals": len(tree.terminals), "counts": tree.counts(),
                "max_own_decisions": tree.depth_of_own_decisions()}
        print(f"{key:<34} solving ({len(tree.nodes)} nodes, crowd {pay.crowd}) ...", flush=True)
        sol = solve3.solve_icm(tree, pay, target, "cfr+", check_every=grid.CHECK_EVERY,
                               max_iters=20000)
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
    argv = sys.argv[1:]
    if "--all" in argv:
        stacks = ALL_STACKS
    elif "--stacks" in argv:
        i = argv.index("--stacks")
        stacks = tuple(float(x) for x in argv[i + 1:] if not x.startswith("-"))
    else:
        stacks = DEFAULT_STACKS
    fp = prov.fingerprint()
    plan = [(s, lab, left, n, st) for s in ("small", "big")
            for lab, left in S.stages(s)[:2] for n in (2, 3, 6, 9) for st in stacks]
    (OUT / "RUN.json").write_text(json.dumps(
        {"tier": "1.5", "code_fingerprint": fp, "code": prov.digests(), "build": BUILD15,
         "lifetime_eps": grid.TARGET, "model_fidelity": grid.MODEL_FIDELITY,
         "eps_n2": grid.EPS_N2, "check_every": grid.CHECK_EVERY, "method": "cfr+",
         "max_iters": 20000, "commit": "b75e315",
         "plan": [f"{s}-{lab}-n{n}-{st:g}bb-left{left}" for s, lab, left, n, st in plan]},
        indent=1))
    print(f"Tier 1.5 | fingerprint {fp} | {len(plan)} cells planned | stacks {stacks}", flush=True)
    for setting, label, left, n, stack in plan:
        one(setting, n, stack, left, label)


if __name__ == "__main__":
    main()
