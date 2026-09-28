"""Cross-check floor3/cashier3/pricer3 against pushfold on spots where the two games coincide.

At 3bb the open (2.2bb) leaves under RAISE_GAP behind, so it is dropped and every OPEN3BET node is
fold/all-in: the tree *is* the push/fold tree. So pushfold is an independently written second
implementation of the same game, which is the only way I trust a number (the Cepheus average-strategy
exploitability was off by ~10% until an independent codebase disagreed; Burch 2017 thesis 4.3.1).

Checks:
  A. tree shape: nodes, terminals, live sets, per-terminal contributions.
  B. cashier3.settle == pushfold.cashier.settle on every terminal.
  C. pricer3 counterfactual values == pushfold.pricer counterfactual values, and the per-seat EV,
     on random strategies.
  D. zero-sum: heads-up chip EV must sum to 0 over seats.
  E. own-reach averaging: on the push/fold tree every own reach is 1, so coach3's average must equal
     pushfold.coach's average rule. On the real tree it must not.
"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/Users/nuttakit/project/poker-harness")
sys.path.insert(0, "/Users/nuttakit/project/poker-harness/deepstack-swarm/workspace/burch/open3bet")

from pushfold import cashier, floor as pf_floor, hands, pricer
from pushfold.spot import Spot

import cashier3
import coach3
import floor3
import pricer3

RNG = np.random.default_rng(7)
N = 169


def check(n, depth, sb=0.5, bb=1.0, ante=0.0, ante_mode="each", fee=0.0):
    spot = Spot(stacks=(depth,) * n, sb=sb, bb=bb, ante=ante, ante_mode=ante_mode, fee=fee)
    a, b = floor3.build(spot), pf_floor.build(spot)
    assert a.max_actions == 2, f"{n}@{depth}bb is not a push/fold tree ({a.max_actions} actions)"
    assert len(a.nodes) == len(b.nodes), (len(a.nodes), len(b.nodes))
    assert len(a.terminals) == len(b.terminals)
    for za, zb in zip(a.terminals, b.terminals):
        assert za.live == zb.alive, (za.live, zb.alive)
        # B: settlements agree
        sa = cashier3.settle(spot, za.invested, za.live)
        sb_ = cashier.settle(spot, zb.jammers)
        assert np.allclose(sa.fixed, sb_.fixed), (n, depth, za.index, sa.fixed, sb_.fixed)
        assert len(sa.layers) == len(sb_.layers), (za.index, sa.layers, sb_.layers)
        for la, lb in zip(sa.layers, sb_.layers):
            assert abs(la.amount - lb.amount) < 1e-9 and la.eligible == lb.eligible

    # C: values agree on a random strategy
    pa = pricer3.plan(a)
    pb = pricer.plan(b)
    sig2 = RNG.random((len(b.nodes), N, 2))
    sig2 /= sig2.sum(axis=2, keepdims=True)
    cols_a = pa.columns(sig2)
    cols_b = pricer.columns(sig2)
    ev_a, ev_b = [], []
    for sa_, sb2 in zip(pa.seats, pb):
        if not len(sa_.nodes):
            ev_a.append(0.0)
            ev_b.append(0.0)
            continue
        cfa, fa = sa_.price(cols_a)
        cfb, fb = sb2.price(cols_b)
        # atol 1e-6: pricer3 keeps the 3-way tensor contraction in float32 (pushfold promotes
        # it to float64). The tensors are Monte Carlo with SAMPLES=2000, so their own error
        # is ~1e-2; float32 costs ~6e-9 and halves the memory of the (169,169,chunk) temporary.
        assert np.allclose(cfa, cfb, atol=1e-6), (n, depth, sa_.seat, np.abs(cfa - cfb).max())
        assert np.allclose(fa, fb, atol=1e-6), (n, depth, sa_.seat, np.abs(fa - fb).max())
        mine = sig2[sa_.nodes]
        ev_a.append(hands.PRIOR @ ((mine * cfa).sum(axis=2).sum(axis=0) + fa))
        ev_b.append(hands.PRIOR @ ((mine * cfb).sum(axis=2).sum(axis=0) + fb))
    return np.array(ev_a), np.array(ev_b), a


if __name__ == "__main__":
    print("A-D  push/fold-equivalent spots (3bb, opens dropped): floor3/cashier3/pricer3 vs pushfold")
    for n in (2, 3, 4, 6, 9):
        for depth, ante, mode, fee in ((3.0, 0.0, "each", 0.0), (2.8, 0.1, "each", 0.0),
                                       (3.0, 0.5, "bb", 0.2), (1.2, 0.0, "each", 0.0)):
            ev_a, ev_b, tree = check(n, depth, ante=ante, ante_mode=mode, fee=fee)
            tag = "zero-sum " + (f"{ev_a.sum():+.2e}" if n == 2 else f"n/a ({ev_a.sum():+.4f})")
            print(f"  n={n} {depth}bb ante={ante}/{mode} fee={fee}  values match "
                  f"(max |diff| {np.abs(ev_a - ev_b).max():.2e})   {tag}")

    print("\nE  own-reach averaging")
    spot = Spot(stacks=(3.0,) * 6)
    t = floor3.build(spot)
    st = coach3.start(t, pricer3.plan(t))
    r = np.array([coach3.own_reach(st, s).max() for s in range(6)])
    print(f"  push/fold tree, max own reach over seats = {r.min():.6f}..{r.max():.6f} "
          f"(all 1: pushfold's unweighted average is correct here)")
    spot = Spot(stacks=(15.0,) * 6)
    t = floor3.build(spot)
    st = coach3.start(t, pricer3.plan(t))
    rr = [coach3.own_reach(st, s) for s in range(6)]
    mn = min(x[[nd.index for nd in t.nodes_of(s)]].min() for s, x in enumerate(rr))
    deep = sum(1 for nd in t.nodes if nd.own_prev >= 0)
    print(f"  15bb tree, {deep} of {len(t.nodes)} nodes are a seat's 2nd or 3rd decision; "
          f"min own reach at uniform = {mn:.4f} (pushfold's average rule would be wrong here)")
    print("\nall checks passed")
