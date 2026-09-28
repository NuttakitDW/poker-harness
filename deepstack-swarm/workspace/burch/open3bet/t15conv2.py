import sys
from pathlib import Path
R = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(R)); sys.path.insert(0, str(R/"deepstack-swarm/workspace/burch/open3bet"))
from pushfold.spot import Spot
import floor3 as F, solve3
for label, kw, st in [("tier15@30", dict(tier15=True), (30.,)*3),
                      ("tier1@30",  dict(tier1=True),  (30.,)*3)]:
    t = F.build(Spot(stacks=st), **kw)
    s = solve3.solve(t, 0.0, "cfr+", check_every=200, max_iters=6000)
    print(f"{label}: nodes={len(t.nodes)}", flush=True)
    print("   " + " ".join(f"{it}:{g:.5f}" for it, g in s.history), flush=True)
