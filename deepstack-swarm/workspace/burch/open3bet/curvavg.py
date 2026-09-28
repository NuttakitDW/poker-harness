"""Current vs average strategy at exit. Cepheus shipped the current strategy (thesis 4.3), not the
average Theorem 8 prescribes. Does the same hold here, and does it hold where the average converges
slowly (Tier 1.5 deep)?"""
import sys
from pathlib import Path
R = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(R)); sys.path.insert(0, str(R/"deepstack-swarm/workspace/burch/open3bet"))
from pushfold.spot import Spot
import floor3 as F, coach3, pricer3, seqbr3

CASES = [("t1 3max 15", (15.,)*3, dict(tier1=True), 0.001, 20000),
         ("t1 6max 15", (15.,)*6, dict(tier1=True), 0.001, 20000),
         ("t1 3max 30", (30.,)*3, dict(tier1=True), 0.001, 20000),
         ("t15 3max 15", (15.,)*3, dict(tier15=True), 0.001, 20000),
         ("t15 3max 30", (30.,)*3, dict(tier15=True), 0.001, 30000)]
print(f"{'case':<12}{'iters':>7}{'avg gain':>12}{'cur gain':>12}{'cur better?':>13}", flush=True)
for label, st, kw, tgt, mx in CASES:
    t = F.build(Spot(stacks=st), **kw)
    plan = pricer3.plan(t)
    s = coach3.start(t, plan)
    g = seqbr3.from_floor3(t); aud = seqbr3.FastAuditor(g, plan)
    for it in range(1, mx + 1):
        coach3.iterate(s, "cfr+")
        if it % 25 == 0 and aud.audit(s.average()).exploitability <= tgt:
            break
    a = aud.audit(s.average()).exploitability
    c = aud.audit(s.sigma).exploitability
    print(f"{label:<12}{it:>7}{a:>12.6f}{c:>12.6f}{'YES' if c < a else 'no':>13}", flush=True)
