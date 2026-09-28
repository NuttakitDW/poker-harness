"""Re-measure the re-jam statistic with the off-path nodes taken out.

The Tier 1 tree contains re-jam nodes that no seat's equilibrium strategy can reach: with
n=6 there are 15 "facing exactly one non-all-in raise" nodes, but a seat-0 open is only used
above ~15bb, so at 8-12bb the 9 nodes that require a seat-0 or seat-1 open have reach 0.
CFR+ still assigns them a strategy (jamming 0.6-1.0 there), so a plain mean over all 15 nodes
mixes real decisions with phantom ones, and the *number* of phantom nodes changes with depth.

reach(node) = product of the average strategy along the path to it (edges read off the
terminal paths). Reported per depth:
  all        bowling's statistic, mean P(allin) over every re-jam node
  live       mean over re-jam nodes reachable in BOTH arms (reach > 1e-4)
  rw         reach-weighted mean over re-jam nodes
  dTV_all    max over re-jam nodes of PRIOR-weighted |p_chip - p_icm|
  dTV_live   the same, over nodes live in both arms
  dTV_rw     reach-weighted mean over live nodes

Run: PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/reachadj.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "deepstack-swarm/workspace/burch/open3bet")
from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402

CELLS = Path("deepstack-swarm/workspace/bowling/tier1chart/cells")
OUT = Path("deepstack-swarm/workspace/bard/chartdepth")
ALLIN = 3
N = 6
STACKS = (8.0, 12.0, 15.0, 20.0, 30.0)


def edge_map(tree: floor3.Tree) -> dict[tuple[int, int], int]:
    e: dict[tuple[int, int], int] = {}
    for z in tree.terminals:
        for (n1, a1), (n2, _) in zip(z.path, z.path[1:]):
            e[(n1, a1)] = n2
    return e


def reach(tree: floor3.Tree, sig: np.ndarray, edges) -> np.ndarray:
    r = np.zeros(len(tree.nodes))
    r[0] = 1.0
    for nd in tree.nodes:  # creation order: parents before children
        if r[nd.index] == 0.0:
            continue
        for k, a in enumerate(nd.actions):
            c = edges.get((nd.index, a))
            if c is not None:
                r[c] += r[nd.index] * float(np.mean(sig[nd.index, :, k]))
    return r


def rejam(tree: floor3.Tree) -> list[floor3.Node]:
    return [nd for nd in tree.nodes
            if nd.raises == 1 and ALLIN in nd.actions and 1 not in nd.actions]


def jamvec(sig: np.ndarray, nd: floor3.Node) -> np.ndarray:
    return sig[nd.index, :, list(nd.actions).index(ALLIN)]


def main() -> None:
    rows = []
    for stack in STACKS:
        tree = floor3.build(Spot(stacks=(stack,) * N), tier1=True)
        edges = edge_map(tree)
        c = np.load(OUT / f"chip-n6-{stack:g}bb.npz")["sigma"]
        i = np.load(CELLS / f"small-bubble-n6-{stack:g}bb-left46.npz")["sigma"]
        rc, ri = reach(tree, c, edges), reach(tree, i, edges)
        nds = rejam(tree)
        live = [nd for nd in nds if rc[nd.index] > 1e-4 and ri[nd.index] > 1e-4]
        mc = np.mean([jamvec(c, nd).mean() for nd in nds])
        mi = np.mean([jamvec(i, nd).mean() for nd in nds])
        rw = lambda s, r, ns: (sum(r[nd.index] * jamvec(s, nd).mean() for nd in ns)
                               / sum(r[nd.index] for nd in ns))
        dtv_all = max(float(np.sum(hands.PRIOR * np.abs(jamvec(c, nd) - jamvec(i, nd))))
                      for nd in nds)
        dtv_live = max(float(np.sum(hands.PRIOR * np.abs(jamvec(c, nd) - jamvec(i, nd))))
                       for nd in live)
        dtv_rw = (sum(rc[nd.index] * float(np.sum(hands.PRIOR * np.abs(jamvec(c, nd)
                                                                         - jamvec(i, nd))))
                       for nd in live) / sum(rc[nd.index] for nd in live))
        rows.append((stack, len(nds), len(live), mc, mi, rw(c, rc, nds), rw(i, ri, nds),
                     dtv_all, dtv_live, dtv_rw))

    print("Tier 1, 6-max equal stacks, small/300-runner/45-paid, 46 left, target 0.001.")
    print("Re-jam = mean P(allin) over the 169 classes; dTV = PRIOR-weighted L1 chart distance.")
    print()
    head = (f"{'stack':>6} {'nodes':>6} {'live':>5} | {'all chip':>9} {'all icm':>8} | "
            f"{'rw chip':>8} {'rw icm':>7} | {'dTV_all':>8} {'dTV_live':>9} {'dTV_rw':>8}")
    print(head)
    print("-" * len(head))
    for (s, nn, nl, mc, mi, wc, wi, da, dl, dr) in rows:
        print(f"{s:>6g} {nn:>6} {nl:>5} | {mc:>9.3f} {mi:>8.3f} | "
              f"{wc:>8.3f} {wi:>7.3f} | {da * 100:>7.1f}% {dl * 100:>8.1f}% {dr * 100:>7.1f}%")


if __name__ == "__main__":
    main()
