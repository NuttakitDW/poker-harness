"""Chart-level depth trend: chip EV vs ICM at the re-jam nodes, and the crowd-variant test.

Re-jam node = a seat facing exactly one non-all-in raise in Tier 1 (floor3, tier1=True):
`raises == 1 and actions == (fold, allin)`. Statistic = P(allin) averaged over the 169
classes, per seat, plus the PRIOR-weighted distance between the chip-EV and ICM charts.

Run: PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/chartdepth.py [crowd A...]
  no args        -> chip EV arm only, table of re-jam frequencies
  args are A bb  -> also solve ICM cells with the crowd at that fixed average (extra cost)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "deepstack-swarm/workspace/bowling/tier1chart")
sys.path.insert(0, "deepstack-swarm/workspace/burch/open3bet")
import scenarios as S  # noqa: E402

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402
import solve3  # noqa: E402

CELLS = Path("deepstack-swarm/workspace/bowling/tier1chart/cells")
OUT = Path("deepstack-swarm/workspace/bard/chartdepth")
OUT.mkdir(exist_ok=True)
STACKS = (8.0, 12.0, 15.0, 20.0, 30.0)
N = 6
LEFT = 46
ALLIN = 3


def rejam_nodes(tree: floor3.Tree, seat: int) -> list[floor3.Node]:
    return [nd for nd in tree.nodes_of(seat)
            if nd.raises == 1 and ALLIN in nd.actions and 1 not in nd.actions]


def jam_stats(sigma: np.ndarray, tree: floor3.Tree, seat: int) -> tuple[float, list[float]]:
    """Mean P(allin) over classes at this seat's re-jam nodes, and the per-node vector."""
    vecs = []
    for nd in rejam_nodes(tree, seat):
        k = list(nd.actions).index(ALLIN)
        vecs.append(sigma[nd.index, :, k])
    if not vecs:
        return float("nan"), []
    return float(np.mean(vecs)), vecs


def solve_chip(stack: float, target: float = 0.001) -> np.ndarray:
    cache = OUT / f"chip-n{N}-{stack:g}bb.npz"
    if cache.exists():
        return np.load(cache)["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * N), tier1=True)
    sol = solve3.solve(tree, target, "cfr+", check_every=25, max_iters=20000)
    np.savez_compressed(cache, sigma=sol.st.average())
    print(f"   chip n={N} {stack:g}bb: {sol.history[-1][0]} it {sol.seconds:.1f}s "
          f"gain {sol.history[-1][1]:.6f}", flush=True)
    return sol.st.average()


def solve_icm(stack: float, crowd_stack: float, target: float = 0.001) -> np.ndarray:
    tag = "self" if crowd_stack == stack else f"A{crowd_stack:g}"
    cache = OUT / f"icm-n{N}-{stack:g}bb-{tag}.npz"
    if cache.exists():
        return np.load(cache)["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * N), tier1=True)
    pay = S.payouts("small", N, LEFT, stack) if tag == "self" else \
        S.icm.Payouts(prizes=S.prizes("small"), field=(), crowd=LEFT - N, crowd_stack=crowd_stack)
    sol = solve3.solve_icm(tree, pay, target, "cfr+", check_every=25, max_iters=20000, fast=True)
    np.savez_compressed(cache, sigma=sol.st.average())
    print(f"   icm n={N} {stack:g}bb crowd={crowd_stack:g}: {sol.history[-1][0]} it "
          f"{sol.seconds:.1f}s gain {sol.history[-1][1]:.6f}", flush=True)
    return sol.st.average()


def icm_cell_sigma(stack: float) -> np.ndarray:
    p = CELLS / f"small-bubble-n{N}-{stack:g}bb-left{LEFT}.npz"
    return np.load(p)["sigma"]


def main() -> None:
    variants = [float(a) for a in sys.argv[1:]]
    print(f"Tier 1, {N}-max, equal stacks, small/300-runner/45-paid, {LEFT} left, target 0.001")
    print("Re-jam frequency = mean P(allin) over 169 classes at seats facing one non-all-in raise.")
    print()

    for stack in STACKS:
        tree = floor3.build(Spot(stacks=(stack,) * N), tier1=True)
        kc = solve_chip(stack)
        arms = {"chip": kc, "icm(crowd=self)": icm_cell_sigma(stack)}
        for A in variants:
            arms[f"icm(crowd={A:g})"] = solve_icm(stack, A)
        # dTV between chip and each ICM arm, max over the re-jam nodes of all seats
        dtv = {}
        for name, sig in arms.items():
            if name == "chip":
                continue
            best = 0.0
            for seat in range(1, N):
                _, vc = jam_stats(kc, tree, seat)
                _, vi = jam_stats(sig, tree, seat)
                for a, b in zip(vc, vi):
                    best = max(best, float(np.sum(hands.PRIOR * np.abs(a - b))))
            dtv[name] = best
        print(f"--- {stack:g}bb  (max dTV vs chip EV: "
              + ", ".join(f"{k}={v * 100:.1f}%" for k, v in dtv.items()) + ")")
        print(f"    {'seat':>4} | " + " | ".join(f"{k:>15}" for k in arms))
        for seat in range(1, N):
            row = []
            for name, sig in arms.items():
                m, _ = jam_stats(sig, tree, seat)
                row.append(f"{m:>15.3f}")
            print(f"    {seat:>4} | " + " | ".join(row))
        print()


if __name__ == "__main__":
    main()
