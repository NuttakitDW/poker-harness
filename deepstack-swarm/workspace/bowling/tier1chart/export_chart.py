"""Export a solved Tier 1 cell as chart data a web app can serve.

`scripts/voice/chart_grid.py` renders ANSI for the terminal and its vocabulary is three codes
(`ACTION_CODES = {"raise","call","fold"}`), which cannot express a Tier 1 cell: those have both a
2.2bb open and an all-in, and the shipped producer would print the open under the name "shove". See
`findings/bowling-tier1-chart-format-blocker.md`. This emits neutral JSON with four codes instead,
so the renderer is a presentation choice rather than a data limitation.

Every node a seat actually decides at is exported, not just the first, and the claim sentence
travels with the data (see `findings/bowling-chart-claim-language.md`) so the copy cannot drift from
the evidence.

    .venv/bin/python export_chart.py small bubble 6 15        # one cell to stdout
    .venv/bin/python export_chart.py --all                    # every solved cell -> charts/
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
import scenarios as S  # noqa: E402
from render import label_code  # noqa: E402  the four-code vocabulary, in one place

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402
import floor3  # noqa: E402

CELLS = HERE / "cells"
OUT = HERE / "charts"
ROUND = 3


# johanson, `johanson-model-vs-real-gap.md` (revised 2026-09-28): the model's own error in the
# best-response gain, model vs real deal, in ICM chips/hand. Measured at n=3 EXACT over the whole
# range: 0.0035 (8bb) -> 0.0121 (30bb), and 0.0024 (3 left) -> 0.0070 (bubble) -> 0.0033 (12 left).
# It is NOT a per-seat-count constant: within n=3 alone it spans ~5x with stack and stage.
MODEL_GAP_RANGE = (0.002, 0.013)


def claim(rec: dict) -> str:
    """The sentence this cell is allowed to make.

    At 2 seats heads-up pricing is exact, so the stop rule IS the exploitability. At 3+ the model's
    own pricing error is larger than the stop rule and no stop rule can fix that -- only a better
    pricer. The gap is quoted as a RANGE, not per seat count: johanson measured ~5x variation with
    stack and stage *within* a single seat count, so a per-n point value overstates the precision we
    have. Language suggested by him: largest near the bubble and at deeper stacks.
    """
    n, t = rec["n"], rec["target"]
    if n == 2:
        return (f"solved to {t:g} ICM chips/hand exploitability (exact best response in this model, "
                f"exact heads-up pricing); Tier 1 action set, cap 3")
    lo, hi = MODEL_GAP_RANGE
    # Only draw the contrast where it is real: if the stop rule is already at or above the model's
    # own error, saying "not this number" would be arguing with ourselves.
    contrast = f" The real figure is that error, NOT {t:g}." if t < lo else ""
    return (f"solved to a {t:g} stop rule in a model whose own seat-level pricing error is "
            f"{lo:g}-{hi:g} ICM chips/hand (measured, model vs real deal; largest near the bubble "
            f"and at deeper stacks).{contrast} Tier 1 action set, cap 3")


def _context(nd) -> str:
    """What the seat is looking at. `Node` has no `facing_allin` flag, so derive it: a node is
    facing an all-in exactly when no raise action is offered any more (labels are `fold`, `call`)."""
    if nd.raises == 0:
        return "unopened"
    if not any(lab == "allin" or lab.startswith(("open", "raise")) for lab in nd.labels):
        return "facing all-in"
    return f"facing {nd.raises} raise(s)"


def export(setting: str, label: str, n: int, stack: float) -> dict | None:
    left = dict(S.stages(setting))[label]
    key = f"{setting}-{label}-n{n}-{stack:g}bb-left{left}"
    path = CELLS / f"{key}.json"
    if not path.exists():
        return None
    rec = json.loads(path.read_text())
    if "error" in rec:
        return None
    sig = np.load(CELLS / f"{key}.npz")["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * n), **rec["build"])

    nodes = []
    for seat in range(n):
        for nd in tree.nodes_of(seat):
            codes = [label_code(lab) for lab in nd.labels]
            if any(c is None for c in codes):
                raise SystemExit(f"{key}: unmapped label {nd.labels}")
            per_hand = {}
            for h, name in enumerate(hands.CLASSES):
                sh = sig[nd.index, h, : len(nd.actions)]
                if sh.sum() <= 0:
                    continue
                per_hand[name] = {c: round(float(v), ROUND) for c, v in zip(codes, sh) if v > 0}
            nodes.append({
                "seat": seat, "node": int(nd.index), "context": _context(nd),
                "raises": int(nd.raises), "pot": round(float(nd.pot), 2),
                "actions": list(nd.labels), "codes": codes, "hands": per_hand,
            })

    return {
        "cell": key,
        "meta": {k: rec[k] for k in ("setting", "stage", "n", "stack", "left", "crowd",
                                     "prizes_paid", "target", "unit", "code_fingerprint", "cap",
                                     "build", "converged", "final_gain", "iters", "seconds",
                                     "lifetime_eps")},
        "claim": claim(rec),
        "leaves": rec["counts"],
        "share_convention": "shares over live actions at that node, summed over the 169 classes "
                            "with independent class priors; a hand absent from `hands` is not in "
                            "the range",
        "nodes": nodes,
    }


def main() -> None:
    if "--all" in sys.argv:
        OUT.mkdir(exist_ok=True)
        run = json.loads((CELLS / "RUN.json").read_text())
        done, missing = 0, 0
        for name in run["plan"]:
            m = re.fullmatch(r"(?P<s>[a-z]+)-(?P<l>[a-z]+)-n(?P<n>\d+)-"
                             r"(?P<stack>[\d.]+)bb-left(?P<left>\d+)", name)
            if m is None:
                raise SystemExit(f"unparsable plan entry {name!r}")
            data = export(m["s"], m["l"], int(m["n"]), float(m["stack"]))
            if data is None:
                missing += 1
                continue
            # Compact: this is a serving artifact, not a document. Indented it is 106 MB for the
            # 80 cells; a web app wants the same numbers without the whitespace.
            (OUT / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")))
            done += 1
        print(f"{done} cells exported to {OUT}, {missing} not yet solved")
        return
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    data = export(sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]))
    if data is None:
        raise SystemExit("no solved cell for that spot")
    print(json.dumps(data, indent=1))


if __name__ == "__main__":
    main()
