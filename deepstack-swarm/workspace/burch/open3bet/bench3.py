"""Measured cost of full-width CFR+ on the ICM-OPEN3BET-v0 tree, chip EV, L0 checkdown leaves.

Run:  .venv/bin/python deepstack-swarm/workspace/burch/open3bet/bench3.py [iters]
No stop rule, no tuning, no claim about any strategy: this measures seconds per iteration only.
"""
from __future__ import annotations

import resource
import sys
import time

import numpy as np

sys.path.insert(0, "/Users/nuttakit/project/poker-harness")
sys.path.insert(0, "/Users/nuttakit/project/poker-harness/deepstack-swarm/workspace/burch/open3bet")

from pushfold import coach as pf_coach, floor as pf_floor, hands, icm_pricer, pricer
from pushfold.spot import Spot

import coach3
import floor3
import pricer3


def pushfold_iter_ms(n, depth, payouts=None, reps=3):
    spot = Spot(stacks=(depth,) * n)
    tree = pf_floor.build(spot)
    plans = icm_pricer.plans_for(tree, payouts)
    sigma = np.full((len(tree.nodes), 169, 2), 0.5)
    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        for p in plans:
            if len(p.nodes):
                p.price(pricer.columns(sigma))
        best = min(best, time.perf_counter() - t0)
    return best * 1e3


def main(iters=3):
    print(f"{'n':>3} {'bb':>5} {'nodes':>7} {'seqs':>7} {'terms':>7} {'flop':>6} {'plan s':>8} "
          f"{'s/iter':>9} {'arrays MB':>10} {'peak RSS MB':>12} {'x pushfold':>11}")
    for n in (2, 3, 4, 6, 9):
        for depth in (15.0, 30.0):
            spot = Spot(stacks=(depth,) * n)
            tree = floor3.build(spot)
            try:
                st, planned, per = coach3.run(tree, iters, "cfr+")
            except MemoryError:
                print(f"{n:>3} {depth:>5g} {len(tree.nodes):>7} out of memory")
                continue
            ref = pushfold_iter_ms(n, depth)
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
            print(f"{n:>3} {depth:>5g} {len(tree.nodes):>7} {tree.sequences:>7} "
                  f"{len(tree.terminals):>7} {tree.counts()[floor3.FLOP]:>6} {planned:>8.2f} "
                  f"{per:>9.3f} {st.bytes/1e6:>10.1f} {rss:>12.0f} {per*1e3/ref:>10.1f}x")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
