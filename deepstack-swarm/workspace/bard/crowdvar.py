"""Crowd-composition test: same spot, same chip-EV chart, different field stack.

For each (stack, A) solve the Tier 1 6-max bubble cell with the 40-strong crowd at a FIXED
average A bb instead of at hero's stack (chip-conserving: total chips = 6*stack + 40*A).
Report re-jam frequencies and dTV against the chip-EV chart, beside the crowd-at-hero cell.

Run: PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/crowdvar.py
"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "deepstack-swarm/workspace/bowling/tier1chart")
sys.path.insert(0, "deepstack-swarm/workspace/burch/open3bet")
import scenarios as S  # noqa: E402
from chartdepth import OUT, jam_stats, rejam_nodes, solve_chip  # noqa: E402

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402
import solve3  # noqa: E402

N, LEFT = 6, 46
CASES = [(8.0, 20.0), (8.0, 12.0), (30.0, 20.0), (30.0, 12.0), (30.0, 45.0)]


def sig_for(stack: float, A: float) -> np.ndarray:
    cache = OUT / f"icm-n{N}-{stack:g}bb-A{A:g}.npz"
    if cache.exists():
        return np.load(cache)["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * N), tier1=True)
    pay = S.icm.Payouts(prizes=S.prizes("small"), field=(), crowd=LEFT - N, crowd_stack=A)
    sol = solve3.solve_icm(tree, pay, 0.001, "cfr+", check_every=25, max_iters=20000, fast=True)
    np.savez_compressed(cache, sigma=sol.st.average())
    print(f"   icm {stack:g}bb crowd A={A:g}: {sol.history[-1][0]} it {sol.seconds:.1f}s "
          f"gain {sol.history[-1][1]:.6f}", flush=True)
    return sol.st.average()


def main() -> None:
    for stack, A in CASES:
        tree = floor3.build(Spot(stacks=(stack,) * N), tier1=True)
        kc = solve_chip(stack)
        self_sig = np.load(OUT / f"icm-n{N}-{stack:g}bb-self.npz")["sigma"] \
            if (OUT / f"icm-n{N}-{stack:g}bb-self.npz").exists() else None
        if self_sig is None:
            from chartdepth import icm_cell_sigma
            self_sig = icm_cell_sigma(stack)
        sig = sig_for(stack, A)
        arms = {"icm(crowd=hero)": self_sig, f"icm(crowd={A:g})": sig}
        line = []
        for name, s in arms.items():
            best = 0.0
            for seat in range(1, N):
                _, vc = jam_stats(kc, tree, seat)
                _, vi = jam_stats(s, tree, seat)
                for a, b in zip(vc, vi):
                    best = max(best, float(np.sum(hands.PRIOR * np.abs(a - b))))
            line.append(f"{name} dTV={best * 100:.1f}%")
        print(f"--- {stack:g}bb, crowd A={A:g} => " + " | ".join(line))
        for seat in range(1, N):
            vals = [f"{jam_stats(s, tree, seat)[0]:.3f}" for s in arms.values()]
            print(f"    seat {seat}: chip {jam_stats(kc, tree, seat)[0]:.3f} | "
                  + " | ".join(f"{k} {v}" for (k, _), v in zip(arms.items(), vals)))
        print()


if __name__ == "__main__":
    main()
