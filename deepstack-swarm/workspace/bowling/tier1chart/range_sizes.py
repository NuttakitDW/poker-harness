"""How tight is Tier 1's 'jam or fold' at depth? Seat 0's decision nodes, per stack."""
import json, sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3])); sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
from pushfold import hands
from pushfold.spot import Spot
import floor3

def shares(sig, nd):
    v = sig[nd.index, :, : len(nd.actions)]
    return {a: float(v[:, k].mean()) for k, a in enumerate(nd.labels)}

for stack in (8.0, 12.0, 15.0, 20.0, 30.0):
    key = f"small-bubble-n6-{stack:g}bb-left46"
    p = HERE / "cells" / f"{key}.npz"
    if not p.exists():
        print(f"{key}: not solved yet"); continue
    sig = np.load(p)["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * 6), tier1=True)
    print(f"--- {key}  (6-handed, all stacks {stack:g}bb, bubble) ---")
    for nd in tree.nodes_of(0):
        print(f"   node {nd.index:>3}  raises={nd.raises}  pot={nd.pot:g}bb  acts={nd.labels}  "
              f"mean-shares={ {a: round(x,3) for a,x in shares(sig, nd).items()} }")
