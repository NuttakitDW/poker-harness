"""On an asymmetric table, hero's own BF vector is not a sufficient index.
Candidate second statistic: the covering opponent's own bubble factor when it risks
hero's stack (its call price), and the table-to-field ratio s_table/A.
"""
import importlib.util
import numpy as np
from pushfold import icm
spec = importlib.util.spec_from_file_location("g", "deepstack-swarm/workspace/bard/icm_geometry.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
_, prizes, _ = g.load("mtt_300_players.json")

st = (10.,) + (25.,)*5
for label, left, A in [("pre-bubble 60 A12", 60, 12.), ("FT 9 A20", 9, 20.),
                       ("bubble 46 A20", 46, 20.), ("ITM 27 A20", 27, 20.)]:
    P, cs = g.payouts_for(prizes, left, st, A)
    hero_bf = g.bfs(st, P)[0]
    # opponent 1's BF when it risks x = hero's stack against hero
    s = np.array(st); x = min(s[0], s[1])
    rows = []
    for d in (0., -x, +x):
        r = s.copy(); r[1] += d; r[0] -= d
        rows.append(r)
    v = icm.value(np.array(rows), tuple(s), P)
    opp_bf = (v[0,1]-v[1,1])/(v[2,1]-v[0,1])
    print(f"  {label:<20} crowd={cs:>6.1f}bb  table/field ratio={np.mean(st)/A:5.2f}  "
          f"hero BF={hero_bf:.3f}   covering-opp BF vs hero={opp_bf:.3f}")
