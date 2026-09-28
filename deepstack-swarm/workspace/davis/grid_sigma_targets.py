"""sigma_hand against convergence level, inside ONE solve.

`davis-lifetime-eps.md` sec 2 showed sigma_hand at the 10bb bubble spot moves <0.5% between
solver targets 0.0005 and 0.003, which is why a single eps is usable as a stop rule. That was
push/fold at one spot. The Tier 1 grid needs the same statement at its own spots, especially at
n=9, where reaching target 0.0006 costs thousands of CFR+ iterations.

So: run CFR+ once, save `st.average()` at a ladder of iteration counts, and for each checkpoint
report (exact max gain from `fasticm3.FastAuditor`, sigma_hand from self-play, eps). If sigma is
flat along that ladder, a sigma measured at a cheap target is the sigma the grid's target would
give, and no re-solve is needed to re-target the grid.

    PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_sigma_targets.py \
        --setting small --n 9 --stack 8 --iters 200,500,1000,2000,4000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[2]
for p in (ROOT,
          ROOT / "deepstack-swarm" / "workspace" / "burch" / "open3bet",
          ROOT / "deepstack-swarm" / "workspace" / "bowling" / "tier1chart"):
    sys.path.insert(0, str(p))

import coach3                                     # noqa: E402
import fasticm3                                   # noqa: E402
import icm_pricer3                                # noqa: E402
import seqbr3                                     # noqa: E402
import scenarios as S                             # noqa: E402

from grid_sigma import (LIFETIME, Z, audit_icm, cell_key, describe, game_and_payouts,  # noqa: E402
                        simulate, to_icm)


def run(setting: str, label: str, n: int, stack: float, iters: list[int],
        hands: int, seed: int) -> dict:
    left = dict(S.stages(setting))[label]
    tree, game, payouts = game_and_payouts(setting, n, stack, left)
    plan = icm_pricer3.plan(tree, payouts)
    st = coach3.start(tree, plan)
    aud = fasticm3.FastAuditor(game, fasticm3.plan(tree, payouts, plan), payouts)
    key = cell_key(setting, label, n, stack, left)
    print(f"{key}: {len(tree.nodes)} nodes, crowd {payouts.crowd}, "
          f"ladder {iters}, {hands} hands", flush=True)

    rows = []
    done = 0
    t0 = time.perf_counter()
    for target_it in iters:
        for _ in range(target_it - done):
            coach3.iterate(st, "cfr+")
        done = target_it
        sigma = st.average()
        gain = aud.audit(sigma).exploitability
        raw = simulate(game, sigma, hands, seed)
        net = to_icm(raw, tree.spot.stacks, payouts)
        per = describe(net)
        smax = max(p["sigma"] for p in per)
        smin = min(p["sigma"] for p in per)
        secs = time.perf_counter() - t0
        seat_line = ", ".join(f"{p['sigma']:.4f}" for p in per)
        print(f"  it {target_it:>6}  gain {gain:.6f}  sigma {smin:.4f}-{smax:.4f} "
              f"eps_max {1e3 * Z * smax / np.sqrt(LIFETIME):.4f} mICM/hand  "
              f"per-seat [{seat_line}]  {secs:.0f}s", flush=True)
        rows.append(dict(iters=target_it, gain=gain, sigma_max=smax, sigma_min=smin,
                         eps_max=Z * smax / np.sqrt(LIFETIME), per_seat=per,
                         seconds=round(secs, 1)))
    return dict(cell=key, setting=setting, stage=label, n=n, stack=stack, left=left,
                crowd=payouts.crowd, nodes=len(tree.nodes), hands=hands, seed=seed,
                ladder=rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--setting", required=True)
    ap.add_argument("--stage", default="bubble")
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--stack", type=float, required=True)
    ap.add_argument("--iters", default="200,500,1000,2000,4000")
    ap.add_argument("--hands", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    iters = [int(x) for x in a.iters.split(",")]
    rec = run(a.setting, a.stage, a.n, a.stack, iters, a.hands, a.seed)
    out = a.out or str(HERE / f"grid_targets_{a.setting}-{a.stage}-n{a.n}-{a.stack:g}bb.json")
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=1)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
