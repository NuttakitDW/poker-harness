import time, json
import numpy as np
from pushfold import coach, icm
from pushfold.spot import Spot
import importlib.util
spec = importlib.util.spec_from_file_location("g", "deepstack-swarm/workspace/bard/icm_geometry.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

name, prizes, chips = g.load("mtt_300_players.json")
for n in (2, 6, 9):
    st = (15.0,) * n
    P, cs = g.payouts_for(prizes, 46, st, 20.0)
    sp = Spot(stacks=st, ante=0.0)
    t = time.perf_counter()
    r = coach.solve(sp, method="cfr+", target=0.01, check_every=25, max_iters=200, payouts=P)
    print(f"{n}-max  iters={r.iterations}  exploit={r.exploitability:.5f}  {time.perf_counter()-t:.1f}s"
          f"  crowd_stack={cs:.1f}  first-in range%={r.range_pct(0)*100:.1f}")
