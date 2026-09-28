import sys, time
from pathlib import Path
R = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(R)); sys.path.insert(0, str(R/"deepstack-swarm/workspace/burch/open3bet"))
from pushfold.spot import Spot
from pushfold import icm
import floor3 as F, solve3

print("D. Tier 1.5 chip-EV solves, equal stacks, target 0.001, cfr+", flush=True)
for n, st in [(3, (15.,)*3), (6, (15.,)*6)]:
    t = F.build(Spot(stacks=st), tier15=True)
    s = solve3.solve(t, 0.001, "cfr+", check_every=25, max_iters=20000)
    print(f"  n={n}: nodes={len(t.nodes)} terms={len(t.terminals)} {t.counts()}", flush=True)
    print(f"     converged={s.converged} iters={s.history[-1][0]} gain={s.history[-1][1]:.6f} "
          f"{s.seconds:.1f}s ({s.seconds/s.history[-1][0]*1000:.1f} ms/iter)", flush=True)

print("E. Tier 1.5 ICM solve, equal stacks 15bb, target 0.0006", flush=True)
t = F.build(Spot(stacks=(15.,)*6), tier15=True)
pay = icm.Payouts(prizes=(50., 30., 20.), crowd=40, crowd_stack=15.)
s = solve3.solve_icm(t, pay, 0.0006, "cfr+", check_every=25, max_iters=20000)
print(f"  converged={s.converged} iters={s.history[-1][0]} gain={s.history[-1][1]:.6f} {s.seconds:.1f}s", flush=True)
print("DONE", flush=True)
