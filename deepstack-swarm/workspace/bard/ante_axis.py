"""Does the ante need its own grid axis? 6-max, bubble stage (46 left, A=20), hero 10bb."""
import importlib.util
from pushfold import coach
from pushfold.spot import Spot
spec = importlib.util.spec_from_file_location("g", "deepstack-swarm/workspace/bard/icm_geometry.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
gr = importlib.util.spec_from_file_location("gr", "deepstack-swarm/workspace/bard/grid_resolution.py")
grm = importlib.util.module_from_spec(gr); gr.loader.exec_module(grm)
_, prizes, _ = g.load("mtt_300_players.json")
st = (10.,)*6
P, _ = g.payouts_for(prizes, 46, st, 20.)
base = None
for mode, ante in [("each", 0.0), ("bb", 0.5), ("bb", 1.0), ("bb", 1.25), ("each", 0.125), ("each", 0.2)]:
    r = coach.solve(Spot(stacks=st, ante=ante, ante_mode=mode), method="cfr+",
                    target=grm.TARGET, check_every=25, max_iters=grm.MAXIT, payouts=P)
    line = f"  ante_mode={mode:<5} ante={ante:<5} UTG first-in={r.range_pct(0)*100:5.1f}%  SB={r.range_pct(4)*100:5.1f}%  exploit={r.exploitability:.4f}"
    if base is None: base = r
    elif base.strategy.shape == r.strategy.shape:
        line += f"   dTV vs no-ante={grm.dist(base, r)[1]*100:5.2f}%"
    print(line)
