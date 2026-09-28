"""Render a solved Tier 1 cell as a 13x13 chart with FOUR codes, not three.

Why this file exists. `scripts/voice/chart_grid.py` fixes the vocabulary at
`ACTION_CODES = {"raise": "R", "call": "C", "fold": "F"}` and resolves an unknown action to fold,
and its producer `pushfold_chart._cells` is binary by construction (`code = "C" if action == "call"
else "R"`, then a 0.5 threshold). Fed a Tier 1 solution -- whose unopened labels are
`['fold', 'open 2.2', 'allin']` -- that pipeline would print the min-raise under the name "shove".
See `findings/bowling-tier1-chart-format-blocker.md`.

This is the proof that the fix is a fourth code and not a new mechanism. It is a *demonstration*,
not a patch to `scripts/`: nothing here is imported by production, and `scripts/` is untouched.

    .venv/bin/python render.py small bubble 3 15

Codes: F fold, R a non-all-in raise (the open), J all-in, C call.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
import scenarios as S  # noqa: E402

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402

CELLS = HERE / "cells"
# The whole vocabulary change, in one line. 'raise' stays R for a non-all-in raise; J is new.
ACTION_CODES = {"fold": "F", "raise": "R", "call": "C", "allin": "J"}


def label_code(label: str) -> str | None:
    """Map one solver label to a chart code, or None if it is not an action we know.

    Labels carry amounts (`call 12.8`, `open 2.2`), so this matches on the leading word and must
    never fall back to a default -- a silent fallback to 'F' is exactly the bug being fixed.
    """
    word = label.split()[0].lower()
    if word in ("fold", "allin", "check"):
        return ACTION_CODES.get(word)
    if word in ("call", "raise"):
        return ACTION_CODES[word]
    if word == "open":
        return ACTION_CODES["raise"]
    return None


def render(setting: str, label: str, n: int, stack: float, seat: int = 0) -> None:
    left = dict(S.stages(setting))[label]
    key = f"{setting}-{label}-n{n}-{stack:g}bb-left{left}"
    rec = json.loads((CELLS / f"{key}.json").read_text())
    sig = np.load(CELLS / f"{key}.npz")["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * n), tier1=True)

    nodes = [nd for nd in tree.nodes_of(seat) if nd.raises == 0]
    if len(nodes) != 1:
        print(f"{key}: {len(nodes)} unopened seat-{seat} nodes; expected 1")
        return
    nd = nodes[0]
    codes = [label_code(lab) for lab in nd.labels]
    if any(c is None for c in codes):
        raise SystemExit(f"unmapped label in {nd.labels}")
    print(f"# {key}  seat {seat}, unopened")
    print(f"# gain {rec['final_gain']:.6f} ICM chips/hand over {rec['iters']} iters, "
          f"target {rec['target']}, fingerprint {rec.get('code_fingerprint')}")
    print(f"# labels {nd.labels} -> codes {codes}")
    print(f"# column order: " + "  ".join(f"{c}={l}" for c, l in zip(codes, nd.labels)))
    print()
    for r in range(13):
        row = []
        for c in range(13):
            h = r * 13 + c
            shares = sig[nd.index, h, : len(nd.actions)]
            top = int(np.argmax(shares))
            row.append(f"{hands.CLASSES[h]:>2}{codes[top]}{shares[top]:.1f}")
        print(" ".join(row))


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]),
           int(sys.argv[5]) if len(sys.argv) > 5 else 0)
