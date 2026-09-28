"""Tier 1 at the newly set targets, per seed, plus dTV under davis's exact convention.

New targets (bowling, 2026-09-27): 0.001 bb/hand chip EV, 0.0006 ICM chips/hand.

Two jobs:
  1. Solve the 6-handed 15bb Tier 1 spot under each table seed with the *real* stop rule
     (`solve3.solve` / `solve3.solve_icm`) at those targets. Report iterations and the final
     exact exploitability, and cross-audit each final profile on the other seeds' tables.
  2. Recompute the chart dTV under davis's convention -- action index 1 only
     (`noise_floor.py` line 72-73: |s1[:,:,1] - s2[:,:,1]| weighted by PRIOR, max over nodes)
     as well as this finding's max-over-legal-actions -- so the two trees' numbers are directly
     comparable.

    .venv/bin/python deepstack-swarm/workspace/burch/seednoise/targets.py
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "open3bet")]

from tableswap import install_seed  # noqa: E402

from pushfold import hands, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import floor3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402
import solve3  # noqa: E402

SEEDS = ("A", "B", "C")
TARGET = {"chip": 0.001, "icm": 0.0006}
CHECK = {"chip": 25, "icm": 200}
PRIOR = hands.PRIOR


def main() -> None:
    tree = floor3.build(Spot(stacks=(15.0,) * 6), tier1=True)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=())

    solved: dict[str, dict] = {}
    for name in SEEDS:
        install_seed(name)
        for mode in ("chip", "icm"):
            t0 = time.perf_counter()
            if mode == "chip":
                s = solve3.solve(tree, TARGET[mode], "cfr+", CHECK[mode], 20000)
                sigma = s.st.average()
            else:
                s = solve3.solve_icm(tree, payouts, TARGET[mode], "cfr+", CHECK[mode], 20000)
                sigma = s.st.average()
            it, val = s.history[-1]
            print(f"[{name}] {mode}: {'converged' if s.converged else 'NO'} at iter {it}, "
                  f"exact {val:.6f} {'bb/hand' if mode=='chip' else 'ICM chips/hand'}, "
                  f"{time.perf_counter()-t0:.1f}s", flush=True)
            solved[f"{mode}|{name}"] = {"iters": it, "value": val, "converged": s.converged}
            np.savez_compressed(HERE / f"target-{name}-{mode}.npz", sigma=sigma)

    # cross-audit the newly converged profiles
    print("\ncross-audit of the newly converged profiles", flush=True)
    for mode in ("chip", "icm"):
        for audit_seed in SEEDS:
            install_seed(audit_seed)
            if mode == "chip":
                aud = seqbr3.FastAuditor(seqbr3.from_floor3(tree), pricer3.plan(tree))
            else:
                aud = seqbr3.Auditor(seqbr3.from_floor3(tree), payouts)
            for solve_seed in SEEDS:
                sigma = np.load(HERE / f"target-{solve_seed}-{mode}.npz")["sigma"]
                v = float(aud.audit(sigma).exploitability)
                solved[f"{mode}|{solve_seed}|{audit_seed}"] = v
                print(f"  {mode} {solve_seed}->{audit_seed} {v:.6f}", flush=True)

    # ---------------------------------------------------------------- dTV, both conventions
    print("\nchart dTV", flush=True)
    dtv = {}
    for mode in ("chip", "icm"):
        s = {n: np.load(HERE / f"target-{n}-{mode}.npz")["sigma"] for n in SEEDS}
        for x, y in itertools.combinations(SEEDS, 2):
            d = np.abs(s[x] - s[y])
            w = PRIOR[None, :, None] * d
            dtv[f"{mode}|{x}{y}"] = {
                "davis_index1_pct": float((PRIOR[None, :] * d[:, :, 1]).sum(axis=1).max() * 100),
                "max_over_actions_pct": float(w.sum(axis=1).max(axis=1).max() * 100),
            }
            print(f"  {mode} {x}{y}: davis-convention {dtv[f'{mode}|{x}{y}']['davis_index1_pct']:.3f}%  "
                  f"max-over-actions {dtv[f'{mode}|{x}{y}']['max_over_actions_pct']:.3f}%", flush=True)

    (HERE / "targets.json").write_text(json.dumps({"solved": solved, "dtv": dtv}, indent=1))
    print("\nwrote", HERE / "targets.json")


if __name__ == "__main__":
    main()
