"""Final tables for the FLOP-gap A/B, read from the saved json/npz (no re-solving).

Usage: .venv/bin/python summary.py [spot mode ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "open3bet"))

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import floor3  # noqa: E402

CONFIGS = [("3max", "chip"), ("6max", "chip"), ("ladder", "chip"), ("2short", "chip"),
           ("3max", "icm"), ("6max", "icm"), ("ladder", "icm")]
SPOTS = {"3max": (5.0, 15.0, 30.0), "6max": (4.0, 8.0, 15.0, 20.0, 30.0, 15.0),
         "ladder": (5.0, 10.0, 15.0, 20.0, 25.0, 30.0),
         "2short": (2.0, 15.0, 15.0, 15.0, 15.0, 15.0)}
ARMS = (("asis", {}, None), ("leafree", {"behind_cap": 1}, None), ("stackoff", {}, 1.0))


def build(stacks, kw, dial):
    import ab as A
    tree = floor3.build(Spot(stacks=stacks), tier1=True, **kw)
    return A.stackoff(tree, dial) if dial is not None else tree


def argmax_shift(spot, mode, arm):
    """PRIOR-weighted share of the 169 classes where the first-in argmax action differs."""
    napz = np.load(HERE / f"ab-{spot}-{mode}.npz")
    if f"{arm}_sigma" not in napz:
        return None
    sa = napz["asis_sigma"]
    sb = napz[f"{arm}_sigma"]
    ta = build(SPOTS[spot], {}, None)
    tb = dict((a, (k, d)) for a, k, d in ARMS)[arm]
    t2 = build(SPOTS[spot], tb[0], tb[1])
    n0a = [nd for nd in ta.nodes if nd.seat == 0 and not nd.history][0]
    n0b = [nd for nd in t2.nodes if nd.seat == 0 and not nd.history][0]
    k = len(n0a.actions)
    a1 = sa[n0a.index, :, :k].argmax(axis=1)
    a2 = sb[n0b.index, :, :k].argmax(axis=1)
    diff = a1 != a2
    return float(hands.PRIOR[diff].sum())


def main() -> None:
    cfgs = [tuple(c) for c in (sys.argv[1:] and [sys.argv[1:]] or CONFIGS)]
    if sys.argv[1:]:
        cfgs = [(sys.argv[1], sys.argv[2])]
    for spot, mode in CONFIGS:
        p = HERE / f"ab-{spot}-{mode}.json"
        if not p.exists():
            continue
        rec = json.loads(p.read_text())
        print(f"\n=== {spot} {rec['stacks']} {mode} target={rec['target']}")
        print(f"{'arm':>9} {'iters':>6} {'gain':>9} {'flopReach':>9} {'P(fold)':>7} "
              f"{'P(open)':>7} {'P(jam)':>7} {'jamRange':>8} {'mean|dS|':>8} {'max|dS|':>8} "
              f"{'argmaxShift':>11}")
        for arm in ("asis", "leafree", "stackoff"):
            if arm not in rec["arms"]:
                continue
            a = rec["arms"][arm]
            fi = a.get("short_firstin", {})
            cd = rec["chart_diff"].get(arm, {}) if arm != "asis" else {}
            sh = argmax_shift(spot, mode, arm) if arm != "asis" else 0.0
            print(f"{arm:>9} {a['iters']:>6} {a['final_gain']:>9.6f} {a['flop_reach_total']:>9.5f} "
                  f"{fi.get('P(fold)', float('nan')):>7.3f} {fi.get('P(raise)', 0.0):>7.3f} "
                  f"{fi.get('P(allin)', 0.0):>7.3f} {fi.get('range_allin', 0.0):>8.3f} "
                  f"{cd.get('mean_abs_dsigma_prior', 0.0):>8.4f} {cd.get('max_abs_dsigma', 0.0):>8.3f} "
                  f"{sh:>11.3f}")
        cj = rec["arms"]["asis"].get("conditional_on_short_firstin", {}).get("allin", {})
        if cj:
            print(f"   flop | short seat jams  = {cj['kind_reach'].get('flop', 0.0):.4f}   "
                  f"(P(jam)={cj['P']:.3f})")


if __name__ == "__main__":
    main()
