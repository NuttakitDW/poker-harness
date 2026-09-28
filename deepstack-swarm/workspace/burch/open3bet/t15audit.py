"""Is the FastAuditor right on a depth-2 (Tier 1.5) tree? Reference Auditor is the oracle."""
import sys
from pathlib import Path
R = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(R)); sys.path.insert(0, str(R/"deepstack-swarm/workspace/burch/open3bet"))
from pushfold.spot import Spot
import floor3 as F, solve3, seqbr3, pricer3, icm_pricer3, fasticm3
from pushfold import icm

for label, st, kw in [("tier15@15", (15.,)*3, dict(tier15=True)),
                      ("tier15@30", (30.,)*3, dict(tier15=True)),
                      ("tier1@30",  (30.,)*3, dict(tier1=True))]:
    t = F.build(Spot(stacks=st), **kw)
    plan = pricer3.plan(t)
    st_ = solve3.__dict__  # noqa
    import coach3
    s = coach3.start(t, plan)
    for _ in range(600):
        coach3.iterate(s, "cfr+")
    sig = s.average()
    g = seqbr3.from_floor3(t)
    fast = seqbr3.FastAuditor(g, plan).audit(sig)
    slow = seqbr3.Auditor(g).audit(sig)
    print(f"{label}: fast={fast.exploitability:.8f} slow={slow.exploitability:.8f} "
          f"|diff|={abs(fast.exploitability-slow.exploitability):.2e} "
          f"| ev diff={abs(fast.ev-slow.ev).max():.2e}", flush=True)
