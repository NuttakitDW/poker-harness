"""Exact size of the ICM-OPEN3BET-v0 tree from floor3.build. Structure only, no pricing."""
from __future__ import annotations

import sys

sys.path.insert(0, "/Users/nuttakit/project/poker-harness")
sys.path.insert(0, "/Users/nuttakit/project/poker-harness/deepstack-swarm/workspace/burch/open3bet")

from pushfold import floor as pf_floor
from pushfold.spot import Spot

import floor3


def row(n: int, depth: float, cap: int = 3):
    spot = Spot(stacks=(depth,) * n)
    t = floor3.build(spot, cap=cap)
    c = t.counts()
    pf = pf_floor.build(spot)
    terms = sum(c.values())
    # pricing work: one "term set" per (terminal, seat that has a decision on the path)
    hits = sum(len(z.decisions_of(s, t.nodes)) for z in t.terminals for s in range(n))
    return dict(n=n, bb=depth, nodes=len(t.nodes), seqs=t.sequences, amax=t.max_actions,
                terms=terms, depth=t.depth_of_own_decisions(), hits=hits,
                pf_nodes=len(pf.nodes), pf_terms=len(pf.terminals), **c)


if __name__ == "__main__":
    keys = ["n", "bb", "nodes", "seqs", "amax", "terms", "allfold", "uncontested",
            "showdown", "flop", "depth", "hits", "pf_nodes", "pf_terms"]
    print("  ".join(f"{k:>11}" for k in keys))
    for n in (2, 3, 4, 6, 9):
        for depth in (5, 8, 10, 15, 20, 30):
            r = row(n, float(depth))
            print("  ".join(f"{r[k]:>11}" if not isinstance(r[k], float) else f"{r[k]:>11g}"
                            for k in keys))
