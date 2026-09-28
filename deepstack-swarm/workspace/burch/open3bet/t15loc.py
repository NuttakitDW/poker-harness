import sys
from pathlib import Path
R = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(R)); sys.path.insert(0, str(R/"deepstack-swarm/workspace/burch/open3bet"))
from pushfold.spot import Spot
import floor3 as F, solve3, seqbr3, pricer3, coach3
import numpy as np

t = F.build(Spot(stacks=(30.,)*3), tier15=True)
plan = pricer3.plan(t)
s = coach3.start(t, plan)
g = seqbr3.from_floor3(t)
aud = seqbr3.FastAuditor(g, plan)
for it in (1000, 3000, 6000, 12000):
    while s.t < it:
        coach3.iterate(s, "cfr+")
    sig = s.average()
    r = aud.audit(sig)
    print(f"iter {it}: max={r.exploitability:.6f} per-seat gains="
          f"{np.round(r.gain,6).tolist()}", flush=True)
print(flush=True)
print("nodes:", flush=True)
for nd in t.nodes:
    print(f"  idx={nd.index} seat={nd.seat} raises={nd.raises} acts={nd.actions} "
          f"to_call={nd.to_call:.2f} raise_to={nd.raise_to:.2f} pot={nd.pot:.2f} "
          f"hist={nd.history}", flush=True)
