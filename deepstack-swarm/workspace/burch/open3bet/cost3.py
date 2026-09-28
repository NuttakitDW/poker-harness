"""Cost of one full-width CFR+ iteration on the ICM-OPEN3BET-v0 tree.

Two independent estimates, on purpose:

(A) Calibration. Time a real `pushfold.coach` iteration (chip EV and ICM) at 3/6/9-handed and
    divide by the number of (terminal, seat) pricing hits. Scale by the new tree's hit count.
    Cheap, and it is the number bowling extrapolated from, so it is comparable.

(B) Kernel floor. Time the showdown kernels themselves at the new tree's terminal counts:
    - 2-way: (169x169 weights) @ (169 x m) rival columns          [pricer._two_way]
    - 3-way: (169 x 169^2) @ (169^2 x m) then einsum              [pricer._three_way]
    - ICM 3-way: the same with 6 finish orders grouped            [icm_pricer._layouts]
    Plus the regret/strategy arithmetic over (nodes, 169, 4).
    This is a floor: it counts no python overhead and no reach bookkeeping.

If (B) is already too slow, no amount of engineering saves full width.
"""
from __future__ import annotations

import sys
import time

import numpy as np

sys.path.insert(0, "/Users/nuttakit/project/poker-harness")
sys.path.insert(0, "/Users/nuttakit/project/poker-harness/deepstack-swarm/workspace/burch/open3bet")

from pushfold import coach, floor as pf_floor, hands, icm, icm_pricer, pricer, structures
from pushfold.spot import Spot

import count3
import floor3

N = 169


def timeit(fn, repeat=3):
    fn()
    best = min(_one(fn) for _ in range(repeat))
    return best


def _one(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def calibrate(n, depth=15.0, payouts=None):
    spot = Spot(stacks=(depth,) * n)
    tree = pf_floor.build(spot)
    plans = icm_pricer.plans_for(tree, payouts)
    sigma = np.full((len(tree.nodes), N, 2), 0.5)

    def one_iter():
        for p in plans:
            if not len(p.nodes):
                continue
            cfv, _ = p.price(pricer.columns(sigma))
            mine = sigma[p.nodes]
            gain = cfv - (mine * cfv).sum(axis=2, keepdims=True)

    ms = timeit(one_iter) * 1e3
    hits = sum(1 for z in tree.terminals for s in range(n) if True) * 1  # one decision per seat max
    hits = sum(len(tree.terminals) for _ in range(n))
    return ms, hits


def kernels(n, depth=15.0):
    """Kernel floor for one iteration at (n, depth), counting 2-way and 3-way terminals."""
    spot = Spot(stacks=(depth,) * n)
    t = floor3.build(spot)
    two = three = 0
    for z in t.terminals:
        if len(z.live) < 2:
            continue
        k = min(len(z.live), 3)
        # every seat with a decision on this path needs this terminal's showdown factor
        hits = sum(len(z.decisions_of(s, t.nodes)) for s in range(n))
        if k == 2:
            two += hits
        else:
            three += hits
    return t, two, three


def time_two(m):
    w = (pricer.opponents(3) * np.ones((N, N))).astype(np.float64)
    cols = np.random.rand(N, m)
    return timeit(lambda: w @ cols) * 1e3


def time_three(m, batch=2048):
    flat = np.random.rand(N * N, N).astype(np.float32)   # as pricer._three_way()
    cols = np.random.rand(N, m).astype(np.float32)
    rival = np.random.rand(N, m).astype(np.float32)

    def run():
        done = 0
        while done < m:
            hi = min(m, done + batch)
            inner = (flat @ cols[:, done:hi]).reshape(N, N, -1)
            np.einsum("hgm,gm->hm", inner, rival[:, done:hi])
            done = hi

    return timeit(run, repeat=1) * 1e3


def arithmetic(nodes, actions=4):
    r = np.zeros((nodes, N, actions))
    g = np.random.rand(nodes, N, actions)

    def run():
        x = np.maximum(r + g, 0.0)
        s = x.sum(axis=-1, keepdims=True)
        np.where(s > 0, x / np.where(s > 0, s, 1), 1.0 / actions)

    return timeit(run) * 1e3


if __name__ == "__main__":
    stage = structures.Stage(entrants=100, left=12)
    print("=== (A) calibration: pushfold full-width iteration, 15bb equal stacks ===")
    print(f"payouts: {stage.curve}, {stage.entrants} entrants, {stage.left} left, {stage.paid} paid")
    cal = {}
    for n in (3, 6, 9):
        ms_chip, hits = calibrate(n)
        pay = stage.payouts(n, 15.0)
        ms_icm, _ = calibrate(n, payouts=pay)
        cal[n] = (ms_chip, ms_icm, hits)
        print(f"n={n}  hits={hits:6d}  chipEV {ms_chip:8.1f} ms/it  "
              f"({1e3*ms_chip/hits:6.1f} us/hit)   ICM {ms_icm:9.1f} ms/it "
              f"({1e3*ms_icm/hits:7.1f} us/hit)  ICM/chip {ms_icm/ms_chip:5.1f}x")

    print("\n=== (B) new tree: size and kernel floor, 15bb equal stacks ===")
    for n in (2, 3, 4, 6, 9):
        t, two, three = kernels(n)
        hits = two + three
        ms2 = time_two(two) if two else 0.0
        ms3 = time_three(three) if three else 0.0
        ms_ar = arithmetic(len(t.nodes))
        floor_ms = ms2 + ms3 + ms_ar
        ref = cal.get(n)
        scaled = f"{ref[0]*hits/ref[2]/1e3:8.2f} s" if ref else "       -"
        scaled_icm = f"{ref[1]*hits/ref[2]/1e3:8.2f} s" if ref else "       -"
        mem = len(t.nodes) * N * 4 * 8 * 3 / 1e6
        print(f"n={n}  nodes={len(t.nodes):6d} terms={len(t.terminals):6d} "
              f"hits={hits:7d} (2w {two:6d} / 3w {three:6d})  "
              f"kernel floor {floor_ms:8.1f} ms  [2w {ms2:6.1f} 3w {ms3:7.1f} arith {ms_ar:5.1f}]  "
              f"scaled-from-pushfold chipEV {scaled}  ICM {scaled_icm}  regret mem {mem:6.1f} MB")
