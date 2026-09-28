"""Controls for the cross-audit: how much does an exploitability number move when ONLY the
3-way tables move, for profiles that did not adapt to those tables?

Two fixed profiles, audited under each seed's tables:
  uniform   -- `coach3.start`'s uniform strategy. Maximally non-adapted.
  early     -- seed A's CFR+ profile after 200 iterations (0.0028 bb/hand chip). Half-converged:
               far enough from equilibrium that the max in `max_i gain_i` has real slack, so the
               first-order term in the table perturbation is visible.

The converged seed-A profile is the third point and comes from the cross-audit in noise.py.
Writes control.json.

    .venv/bin/python deepstack-swarm/workspace/burch/seednoise/control.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from tableswap import install_seed  # noqa: E402

from pushfold import icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import coach3  # noqa: E402
import floor3  # noqa: E402
import icm_pricer3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402

SEEDS = ("A", "B", "C")
EARLY = 200
METHOD = "cfr+"


def main() -> None:
    tree = floor3.build(Spot(stacks=(15.0,) * 6), tier1=True)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=())
    profiles: dict[str, dict[str, np.ndarray]] = {"uniform": {}, "early": {}}

    install_seed("A")
    for mode in ("chip", "icm"):
        if mode == "chip":
            plan = pricer3.plan(tree)
        else:
            plan = icm_pricer3.plan(tree, payouts)
        st = coach3.start(tree, plan)
        profiles["uniform"][mode] = st.average().copy()
        if mode == "icm":
            icm_pricer3.plan(tree, payouts)
        for _ in range(EARLY):
            coach3.iterate(st, METHOD)
        profiles["early"][mode] = st.average().copy()
        print(f"built seed-A profiles for {mode}", flush=True)

    out: dict[str, float] = {}
    for audit_seed in SEEDS:
        install_seed(audit_seed)
        for mode in ("chip", "icm"):
            if mode == "chip":
                plan = pricer3.plan(tree)
                aud = seqbr3.FastAuditor(seqbr3.from_floor3(tree), plan)
            else:
                aud = seqbr3.Auditor(seqbr3.from_floor3(tree), payouts)
            for name, prof in profiles.items():
                v = float(aud.audit(prof[mode]).exploitability)
                out[f"{mode}|{name}|{audit_seed}"] = v
                print(f"  {mode:4s} {name:7s} under {audit_seed}: {v:.6f}", flush=True)

    unit = {"chip": "bb/hand", "icm": "ICM chips/hand"}
    print("\nfixed-profile movement across table seeds")
    for mode in ("chip", "icm"):
        for name in profiles:
            v = [out[f"{mode}|{name}|{s}"] for s in SEEDS]
            print(f"  {mode:4s} {name:7s} {['%.6f' % x for x in v]}  "
                  f"spread {max(v)-min(v):.6f} {unit[mode]}")
    (HERE / "control.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
