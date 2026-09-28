"""Turn the Tier 1 ICM grid cells into a table, and render one cell as a 13x13 chart."""
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


def load() -> list[dict]:
    out = []
    for p in sorted(CELLS.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            print(f"skip unreadable {p.name}")
    return out


def table(recs: list[dict]) -> None:
    ok = [r for r in recs if "error" not in r]
    bad = [r for r in recs if "error" in r]
    print(f"{len(ok)} cells solved, {len(bad)} errored, of {len(recs)}")
    for r in bad:
        print(f"  ERROR {r['cell']}: {r['error']}")
    print()
    head = f"{'setting':<7} {'stage':<8} {'n':>2} {'stack':>6} {'left':>5} {'crowd':>6} " \
           f"{'nodes':>6} {'iters':>6} {'sec':>7} {'gain (ICM chips/hand)':>22}"
    print(head)
    print("-" * len(head))
    for r in sorted(ok, key=lambda r: (r["setting"], r["stage"], r["n"], r["stack"])):
        print(f"{r['setting']:<7} {r['stage']:<8} {r['n']:>2} {r['stack']:>6g} {r['left']:>5} "
              f"{r['crowd']:>6} {r['nodes']:>6} {r['iters']:>6} {r['seconds']:>7.1f} "
              f"{r['final_gain']:>22.6f}")
    over = [r["cell"] for r in ok if r["final_gain"] > r["target"]]
    print(f"\ncells above target {ok[0]['target'] if ok else '?'}: {over or 'none'}")


def chart(setting: str, label: str, n: int, stack: float) -> None:
    """Render seat 0's opening decision of one cell as a 13x13 grid of action shares."""
    left = dict(S.stages(setting))[label]
    key = f"{setting}-{label}-n{n}-{stack:g}bb-left{left}"
    rec = json.loads((CELLS / f"{key}.json").read_text())
    sig = np.load(CELLS / f"{key}.npz")["sigma"]
    tree = floor3.build(Spot(stacks=(stack,) * n), tier1=True)
    first = [nd for nd in tree.nodes_of(0) if nd.raises == 0]
    if len(first) != 1:
        print(f"{key}: {len(first)} unopened seat-0 nodes; expected 1")
        return
    nd = first[0]
    print(f"# {key}   gain {rec['final_gain']:.6f} ICM chips/hand, {rec['iters']} iters")
    print(f"# seat 0 unopened, {nd.labels}, pot {nd.pot}bb, {n} seats, {left} left, "
          f"{rec['prizes_paid']} paid")
    acts = list(nd.labels)
    print("\n# shares per class: " + "  ".join(acts))
    for r in range(13):
        cells = []
        for c in range(13):
            h = r * 13 + c
            v = sig[nd.index, h, : len(nd.actions)]
            cells.append(f"{hands.CLASSES[h]:>3}" + "".join(f"{x:4.2f}" for x in v))
        print("  ".join(cells))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        table(load())
    else:
        chart(sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]))
