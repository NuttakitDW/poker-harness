"""Re-audit already-solved cells with BOTH ICM auditors.

`burch`'s `verify_fasticm3.py` compares the fast and slow auditors on a *random* strategy.
This compares them on the *solved* strategies we are actually going to ship, which is where a
bug that only bites near equilibrium would show up. It also replaces the gain recorded by the
slow-auditor cells with the fasticm3 number so every cell in the grid carries one auditor.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
import scenarios as S  # noqa: E402

from pushfold.spot import Spot  # noqa: E402
import fasticm3  # noqa: E402
import floor3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402

CELLS = HERE / "cells"


def audit_both(rec: dict) -> dict:
    key = rec["cell"]
    npz = CELLS / f"{key}.npz"
    if not npz.exists():
        return {}
    sigma = np.load(npz)["sigma"]
    tree = floor3.build(Spot(stacks=(rec["stack"],) * rec["n"]), tier1=True)
    pay = S.payouts(rec["setting"], rec["n"], rec["left"], rec["stack"])
    game = seqbr3.from_floor3(tree)
    plan = pricer3.plan(tree)
    slow = seqbr3.Auditor(game, pay).audit(sigma)
    fast = fasticm3.FastAuditor(game, fasticm3.plan(tree, pay, plan), pay).audit(sigma)
    return {"slow_gain": float(slow.exploitability), "fast_gain": float(fast.exploitability),
            "diff": abs(float(slow.exploitability) - float(fast.exploitability)),
            "fast_ev": [float(x) for x in fast.ev]}


def main() -> None:
    cells = sorted(CELLS.glob("*.json"))
    n_done = 0
    for p in cells:
        rec = json.loads(p.read_text())
        if "error" in rec or not (CELLS / f"{rec['cell']}.npz").exists():
            continue
        if "fasticm3_gain" in rec:
            continue
        out = audit_both(rec)
        if not out:
            continue
        rec |= {"fasticm3_gain": out["fast_gain"], "slow_auditor_gain": out["slow_gain"],
                "auditor_diff": out["diff"], "auditor": "fasticm3.FastAuditor"}
        rec["final_gain"] = out["fast_gain"]
        p.write_text(json.dumps(rec, indent=1))
        n_done += 1
        print(f"{rec['cell']:<34} slow {out['slow_gain']:.6f} fast {out['fast_gain']:.6f} "
              f"diff {out['diff']:.2e}", flush=True)
    print(f"re-audited {n_done} cells with fasticm3")


if __name__ == "__main__":
    main()
