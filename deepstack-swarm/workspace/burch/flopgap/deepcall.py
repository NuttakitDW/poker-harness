"""Control for the A/B: does the L0 leaf distort the *deep caller's* decision?

The as-is and stack-off arms have the identical tree and action set and differ only in how a FLOP
terminal is priced, so a difference in a node's frequencies between them is the pricing, nothing
else. `leafree` removes the second deep caller as well, so it is confounded on this question.

Reports, over every node where a seat faces an all-in for less than its own stack (so calling
leaves it with chips behind -- the exact action that creates a FLOP terminal), the PRIOR-weighted
P(call). Same nodes in asis and stackoff by index; leafree matched by (seat, actions, history).

Usage: .venv/bin/python deepcall.py <spot> <mode>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/burch/open3bet"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import floor3  # noqa: E402
import ab as A  # noqa: E402

SPOTS = A.SPOTS


def deep_call_nodes(tree: floor3.Tree) -> list[floor3.Node]:
    """Nodes where the actor calls an all-in and keeps chips: the action that makes a FLOP."""
    spot = tree.spot
    room = tuple(spot.stacks[s] - spot.antes[s] for s in range(spot.n))
    out = []
    for nd in tree.nodes:
        if floor3.CALL not in nd.actions:
            continue
        if room[nd.seat] - nd.to_call <= floor3.EPS:
            continue                       # calling puts it in: no chips behind, no FLOP
        # facing an all-in? the CALL is the only non-fold option then
        if len(nd.actions) == 2 and floor3.ALLIN not in nd.actions:
            out.append(nd)
    return out


def main() -> None:
    name, mode = sys.argv[1], sys.argv[2]
    stacks = SPOTS[name]
    napz = np.load(Path(__file__).with_name(f"ab-{name}-{mode}.npz"))
    arms = {}
    for arm, kw, dial in (("asis", {}, None), ("leafree", {"behind_cap": 1}, None),
                          ("stackoff", {}, 1.0)):
        tree = floor3.build(Spot(stacks=stacks), tier1=True, **kw)
        if dial is not None:
            tree = A.stackoff(tree, dial)
        arms[arm] = (tree, napz[f"{arm}_sigma"],
                     {A.node_key(nd): nd.index for nd in tree.nodes})
    ref_tree = arms["asis"][0]
    print(f"{name} {mode}: deep-call nodes (call an all-in, keep chips), P(call) PRIOR-weighted")
    print(f"{'seat':>5} {'to_call':>8} {'hist':>26} {'asis':>8} {'leafree':>8} {'stackoff':>9}")
    tot = {a: [] for a in arms}
    for nd in deep_call_nodes(ref_tree):
        k = floor3.CALL and ref_tree.nodes[nd.index].actions.index(floor3.CALL)
        row = {}
        for arm, (tree, sigma, key) in arms.items():
            j = key.get(A.node_key(nd))
            if j is None:
                row[arm] = float("nan")
                continue
            row[arm] = float(hands.PRIOR @ sigma[j, :, k])
            tot[arm].append((float(hands.PRIOR.sum()), row[arm], nd))
        h = "".join(f"{s}{a}" for s, a in nd.history)[:26]
        print(f"{nd.seat:>5} {nd.to_call:>8.1f} {h:>26} {row['asis']:>8.3f} "
              f"{row['leafree']:>8.3f} {row['stackoff']:>9.3f}")
    print("\nall deep-call nodes, weighted mean P(call):")
    for arm in arms:
        v = [x[1] for x in tot[arm] if not np.isnan(x[1])]
        print(f"  {arm:>9}: n={len(v)} mean={np.mean(v):.4f} max={max(v):.4f} min={min(v):.4f}")


if __name__ == "__main__":
    main()
