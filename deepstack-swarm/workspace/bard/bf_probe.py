"""Probe: is the crowd-model ICM value exactly scale invariant in stack depth?"""
import sys
import numpy as np
sys.path.insert(0, ".")
sys.path.insert(0, "deepstack-swarm/workspace/bowling/tier1chart")
import scenarios as S
from pushfold import icm

for n in (2, 6):
    print(f"--- n={n} table, 40/44 crowd, 46 left, 45 paid")
    for stack in (5.0, 8.0, 12.0, 15.0, 20.0, 30.0, 50.0, 100.0):
        P = S.payouts("small", n, 46, stack)
        s = np.array([stack] * n)
        v = icm.value(s.reshape(1, -1), tuple(s), P)[0]
        # BF for an all-in: hero vs table seat 1, transfer x = stack
        rows = []
        for d in (0.0, -stack, +stack):
            r = s.copy(); r[0] += d; r[1] -= d
            rows.append(r)
        vv = icm.value(np.array(rows), tuple(s), P)
        now, lose, win = vv[0, 0], vv[1, 0], vv[2, 0]
        bf = (now - lose) / (win - now)
        print(f"  S={stack:>6.1f}  V/S={v[0]/stack:.12f}  BF_allin={bf:.12f}")
