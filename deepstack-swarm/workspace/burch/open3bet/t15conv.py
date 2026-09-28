import sys
from pathlib import Path
import numpy as np
R = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(R)); sys.path.insert(0, str(R/"deepstack-swarm/workspace/burch/open3bet"))
from pushfold.spot import Spot
import floor3 as F, solve3

for label, kw in [("tier15@30", dict(tier15=True)), ("tier1@30", dict(tier1=True)),
                  ("tier15@15", dict(tier15=True))]:
    t = F.build(Spot(stacks=(30.,)*3) if "@30" in label else Spot(stacks=(15.,)*3), **kw)
    s = solve3.solve(t, 0.0009, "cfr+", check_every=200, max_iters=40000)
    h = s.history
    print(f"{label}: nodes={len(t.nodes)} conv={s.converged} last={h[-1][1]:.6f} @ {h[-1][0]}", flush=True)
    print("   gain history (every 200):", flush=True)
    for it, g in h[:40]:
        print(f"     {it:>6} {g:.6f}", flush=True)
