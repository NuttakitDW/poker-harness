import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/burch/open3bet"))
import numpy as np
from pushfold.spot import Spot
import floor3, solve3, coach3, pricer3

for stacks in [(5.0, 15.0, 30.0), (4.0, 8.0, 15.0, 20.0, 30.0, 15.0)]:
    spot = Spot(stacks=stacks)
    tree = floor3.build(spot, tier1=True)
    t0 = time.perf_counter()
    st = coach3.start(tree, pricer3.plan(tree))
    for _ in range(20):
        coach3.iterate(st, "cfr+")
    dt = (time.perf_counter() - t0) / 20
    print(f"n={spot.n} {stacks}: {len(tree.nodes)} nodes {len(tree.terminals)} terms, "
          f"{dt*1000:.2f} ms/iter")
