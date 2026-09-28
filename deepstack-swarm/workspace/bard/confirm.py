"""Two confirmations.
A) Is the stack-configuration effect chip geometry rather than ICM? Repeat the config
   sweep with payouts=None (chip EV) and compare the dTV pattern.
B) Does BF-sufficiency survive an ASYMMETRIC table, where BF is a vector? Same
   configuration, many stages; pair up by max |dBF| over opponents.
"""
import importlib.util, itertools
import numpy as np
from pushfold import coach, floor, hands
from pushfold.spot import Spot

spec = importlib.util.spec_from_file_location("g", "deepstack-swarm/workspace/bard/icm_geometry.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
gr = importlib.util.spec_from_file_location("gr", "deepstack-swarm/workspace/bard/grid_resolution.py")
grm = importlib.util.module_from_spec(gr); gr.loader.exec_module(grm)

_, prizes, _ = g.load("mtt_300_players.json")

CFGS = {
    "all 10bb": (10.,)*6, "hero 10 rest 25": (10.,)+(25.,)*5,
    "hero 10 rest 40": (10.,)+(40.,)*5, "hero 10 one60 rest15": (10.,)+(15.,)*4+(60.,),
    "hero 10 blinds 6": (10.,)*4+(6.,6.), "hero 10 blinds 30": (10.,)*4+(30.,30.),
}
print("A) configuration axis under chip EV (no ICM) vs under ICM at the bubble")
base_c = base_i = None
for label, st in CFGS.items():
    rc = coach.solve(Spot(stacks=st), method="cfr+", target=grm.TARGET, check_every=25,
                     max_iters=grm.MAXIT, payouts=None)
    P, _ = g.payouts_for(prizes, 46, st, 20.0)
    ri = coach.solve(Spot(stacks=st), method="cfr+", target=grm.TARGET, check_every=25,
                     max_iters=grm.MAXIT, payouts=P)
    _, mi_ci = grm.dist(rc, ri)      # chip EV vs ICM, same configuration
    line = f"  {label:<22} chipEV-vs-ICM dTV={mi_ci*100:5.2f}%"
    if base_c is None:
        base_c, base_i = rc, ri
    else:
        _, dc = grm.dist(base_c, rc); _, di = grm.dist(base_i, ri)
        line += f"   vs all-10bb: chipEV {dc*100:5.2f}%  ICM {di*100:5.2f}%"
    print(line)

print("\nB) BF-sufficiency on an asymmetric table: hero 10bb, rest 25bb, 6-max")
st = (10.,)+(25.,)*5
rows = []
for label, left in g.STAGES_LIST_300:
    if left < 6: continue
    for A in (12., 20., 30., 45.):
        try: P, cs = g.payouts_for(prizes, left, st, A)
        except Exception: continue
        bf = np.array(g.bfs(st, P))
        r = coach.solve(Spot(stacks=st), method="cfr+", target=grm.TARGET, check_every=25,
                        max_iters=grm.MAXIT, payouts=P)
        rows.append((f"{label} A{A:.0f}", bf, r))
pairs = []
for (l1, b1, r1), (l2, b2, r2) in itertools.combinations(rows, 2):
    _, mx = grm.dist(r1, r2)
    pairs.append((float(np.abs(b1-b2).max()), mx*100, l1, l2))
pairs.sort()
arr = np.array([(p[0], p[1]) for p in pairs])
for lo, hi in [(0,.02),(.02,.05),(.05,.1),(.1,.2),(.2,.5)]:
    m = (arr[:,0]>=lo)&(arr[:,0]<hi)
    if m.sum(): print(f"  max|dBF| in [{lo},{hi}): n={m.sum():4d} dTV mean {arr[m,1].mean():5.2f}% max {arr[m,1].max():5.2f}%")
print("  worst matched pair (max|dBF|<0.05):", max((p for p in pairs if p[0]<0.05), key=lambda p:p[1]))
