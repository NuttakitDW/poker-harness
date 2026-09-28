"""Recon: reproduce bowling's FLOP-terminal counts and print what a FLOP terminal looks like."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/burch/open3bet"))

import numpy as np
from pushfold.spot import Spot
import floor3

SPOTS = {
    "15x6": (15.0,) * 6,
    "6max-uneven": (4.0, 8.0, 15.0, 20.0, 30.0, 15.0),
    "2,15..": (2.0, 15.0, 15.0, 15.0, 15.0, 15.0),
    "ladder5-30": (5.0, 10.0, 15.0, 20.0, 25.0, 30.0),
    "15x3": (15.0,) * 3,
    "3max-uneven": (5.0, 15.0, 30.0),
}

for name, stacks in SPOTS.items():
    spot = Spot(stacks=stacks)
    for tier1 in (True, False):
        tree = floor3.build(spot, tier1=tier1)
        c = tree.counts()
        print(f"{name:>12} tier1={str(tier1):<5} n={spot.n} "
              f"nodes={len(tree.nodes):>4} terms={len(tree.terminals):>4} {c}")
    # detail on FLOP terminals
    tree = floor3.build(spot, tier1=True)
    flops = [z for z in tree.terminals if z.kind == floor3.FLOP]
    print(f"             -- {len(flops)} FLOP terminals, names={spot.names}")
    for z in flops[:8]:
        behind = z.behind(spot)
        print(f"                live={z.live} invested={tuple(round(v,2) for v in z.invested)} "
              f"behind={tuple(round(v,2) for v in behind)} raises={z.raises} "
              f"path_len={len(z.path)}")
    if flops:
        print(f"                ... {len(flops)} total")
    print()
