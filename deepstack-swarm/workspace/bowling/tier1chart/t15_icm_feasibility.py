"""Can Tier 1.5 (the 3bet) be solved with ICM payouts, and what does it cost per cell?

`burch-tier1.5.md` built Tier 1.5 and priced the 3bet in CHIP EV. The shipped grid is Tier 1, so
it has no 3bet -- the user asked for one. This is the feasibility + cost probe for the missing
half: same floor3.build, tier15=True, but with the ICM pricer instead of the chip pricer.

Two questions:
  1. Is a Tier 1.5 tree leaf-free at equal stacks under ICM? (no flop consulted -> the count of
     FLOP terminals must be zero; a nonzero count means the payouts are not all priceable exactly)
  2. How long does one cell take, at n=3/6 and 15bb/30bb, against the same stop rule the Tier 1
     grid uses (`grid.target_for`)?

    .venv/bin/python t15_icm_feasibility.py            # n=3 15bb, the cheap end
    .venv/bin/python t15_icm_feasibility.py 6 30 0.002 # n=6 30bb, the expensive end
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
import scenarios as S  # noqa: E402

from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402
import solve3  # noqa: E402

OUT = HERE / "t15probe"
OUT.mkdir(exist_ok=True)


def run(n: int, stack: float, target: float, setting: str = "small", label: str = "bubble",
        max_iters: int = 20000) -> dict:
    left = dict(S.stages(setting))[label]
    pay = S.payouts(setting, n, left, stack)
    tree = floor3.build(Spot(stacks=(stack,) * n), tier15=True)
    t0 = time.time()
    sol = solve3.solve_icm(tree, pay, target, "cfr+", check_every=25, max_iters=max_iters)
    iters, gain = (sol.history[-1] if sol.history else (0, float("nan")))
    out = {
        "n": n, "stack": stack, "setting": setting, "stage": label, "left": left,
        "tier15": True, "target": target, "seconds": round(sol.seconds, 2),
        "nodes": len(tree.nodes), "terminals": len(tree.terminals),
        "counts": tree.counts(),
        "max_own_decisions": tree.depth_of_own_decisions(),
        "converged": sol.converged, "iters": iters, "final_gain": gain,
        "unit": "ICM chips/hand",
    }
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    stack = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    target = float(sys.argv[3]) if len(sys.argv) > 3 else 0.002
    out = run(n, stack, target)
    print(json.dumps(out, indent=1))
    (OUT / f"t15-n{n}-{stack:g}bb-t{target:g}.json").write_text(json.dumps(out))
