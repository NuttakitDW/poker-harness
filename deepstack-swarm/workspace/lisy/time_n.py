"""Cost per stage at n = 3/6/9, so the deal budget can be picked before spending it."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3]))
sys.path.insert(0, str(HERE.parent / "burch" / "open3bet"))
sys.path.insert(0, str(HERE.parent / "bowling" / "tier1chart"))

import adversary as adv  # noqa: E402
import seqbr  # noqa: E402
import floor3  # noqa: E402
import scenarios as S  # noqa: E402
import seqbr3  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

for n in (3, 6, 9):
    sigma = np.load(HERE / "cells" / f"small-bubble-n{n}-15bb-left46.npz")["sigma"]
    tree = floor3.build(Spot(stacks=(15.0,) * n), tier1=True)
    pay = S.payouts("small", n, 46, 15.0)
    t0 = time.perf_counter()
    game = seqbr3.from_floor3(tree)
    t1 = time.perf_counter()
    Us = {}
    for m in ("model", "onebody", "pairjoint"):
        a = time.perf_counter()
        Us[m] = adv.attacker_u(game, sigma, pay, m)
        Us[m + "_t"] = time.perf_counter() - a
    t2 = time.perf_counter()
    pols = {m: adv.br_policy(game, Us[m], 0) for m in Us if not m.endswith("_t")}
    t3 = time.perf_counter()
    D = 250_000
    deals = adv.real_deals(n, D, seed=1)
    t4 = time.perf_counter()
    base = adv.profile_ev(game, deals, sigma, 0, payouts=pay)
    t5 = time.perf_counter()
    alt = adv.profile_ev(game, deals, sigma, 0, 0, pols["onebody"], payouts=pay)
    t6 = time.perf_counter()
    print(f"n={n}: game {t1-t0:.2f}s | U model {Us['model_t']:.2f} onebody {Us['onebody_t']:.2f} "
          f"pairjoint {Us['pairjoint_t']:.2f} | br {t3-t2:.2f}s | deals {D:,} {t4-t3:.2f}s | "
          f"walk base {t5-t4:.2f}s alt {t6-t5:.2f}s | total {t6-t0:.1f}s")
    d = alt - base
    print(f"      n={n} seat0 onebody gain {d.mean():.6f} (se {d.std(ddof=1)/np.sqrt(D):.1e}) "
          f"[250k deals]")
