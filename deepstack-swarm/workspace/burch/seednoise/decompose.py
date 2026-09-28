"""Where does the table noise go? Split `audit` into profile value and best-response gain.

exploitability = max_seat gain, gain_seat = BR value - profile value. Both are computed from the
same terminal values, so a table perturbation hits both. If the profile is near-optimal the two
shifts cancel and the *reported exploitability* is far more stable than either term. This script
measures both terms for a fixed profile under each seed's tables, so the cancellation is a
measured number rather than a story. It also reports `shortcut` (`pushfold/auditor.py`'s formula),
which on this tree is not a best-response gain (a seat acts up to 3 times).

    .venv/bin/python deepstack-swarm/workspace/burch/seednoise/decompose.py
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

import floor3  # noqa: E402
import icm_pricer3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402

SEEDS = ("A", "B", "C")


def main() -> None:
    tree = floor3.build(Spot(stacks=(15.0,) * 6), tier1=True)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=())
    strat = {"chip": np.load(HERE / "solve-A.npz")["chip_A"],
             "icm": np.load(HERE / "solve-A.npz")["icm_A"]}

    rep: dict[str, dict] = {}
    for mode in ("chip", "icm"):
        per_seat = {"ev": {}, "gain": {}, "shortcut": {}}
        for s in SEEDS:
            install_seed(s)
            if mode == "chip":
                plan = pricer3.plan(tree)
                aud = seqbr3.FastAuditor(seqbr3.from_floor3(tree), plan)
            else:
                aud = seqbr3.Auditor(seqbr3.from_floor3(tree), payouts)
            r = aud.audit(strat[mode])
            per_seat["ev"][s] = r.ev
            per_seat["gain"][s] = r.gain
            per_seat["shortcut"][s] = r.shortcut
            print(f"{mode:4s} {s}: ev={np.round(r.ev, 8).tolist()} "
                  f"gain={np.round(r.gain, 8).tolist()} max={r.exploitability:.8f}", flush=True)

        u = "bb/hand" if mode == "chip" else "ICM chips/hand"
        print(f"\n{mode} ({u}): spread across seeds of a FIXED profile (seed A's, 2000 iters)")
        for term in ("ev", "gain", "shortcut"):
            M = np.array([per_seat[term][s] for s in SEEDS])
            print(f"  {term:9s} per-seat {np.round(M.max(axis=0) - M.min(axis=0), 9).tolist()}"
                  f"   max spread {float((M.max(axis=0) - M.min(axis=0)).max()):.3e}")
        g = np.array([per_seat["gain"][s] for s in SEEDS])          # (seeds, seats)
        ex = g.max(axis=1)                                          # exploitability per seed
        print(f"  exploitability (max over seats of gain) {ex.tolist()}   "
              f"seed spread {float(ex.max() - ex.min()):.3e}")
        rep[mode] = {k: {s: list(map(float, v[s])) for s in SEEDS} for k, v in per_seat.items()}

    (HERE / "decompose.json").write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
