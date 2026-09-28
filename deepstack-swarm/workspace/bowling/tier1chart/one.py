"""Pilot: one Tier 1 ICM cell, timed, to size the full grid."""
from __future__ import annotations
import sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scenarios as S  # noqa: E402
sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))

from pushfold.spot import Spot  # noqa: E402
import floor3, solve3  # noqa: E402

n, stack, setting, left, target = 3, 15.0, "small", 45, 0.0006
tree = floor3.build(Spot(stacks=(stack,) * n), tier1=True)
pay = S.payouts(setting, n, left, stack)
print(f"n={n} stack={stack} {setting} left={left} crowd={pay.crowd} "
      f"target={target} ICM chips/hand | {len(tree.nodes)} nodes {len(tree.terminals)} terminals {tree.counts()}")
t0 = time.perf_counter()
sol = solve3.solve_icm(tree, pay, target, "cfr+", check_every=100, max_iters=3000)
print(f"{'converged' if sol.converged else 'DID NOT converge'} in {sol.history[-1][0]} iters, "
      f"{sol.seconds:.1f}s ({sol.seconds/max(sol.history[-1][0],1)*1000:.1f} ms/iter incl. audits)")
for it, g in sol.history:
    print(f"  iter {it:>5}  {g:.6f}")
