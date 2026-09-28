"""Exact reach of every terminal under a strategy, and per-seat action ranges.

The model deals each seat a class independently from `hands.PRIOR` (pushfold/pricer.py), and a
seat's action at a node is a function of its own class only. So a terminal's reach probability
factorises over seats:

    P(z) = prod_i sum_h PRIOR[h] * prod_{(node,a) in z.path : seat(node)=i} sigma[node][h][a]

which is `prod_i (PRIOR . own_reach_i(last decision))`. Summed over all terminals this must be
1.0; that identity is the self-check.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/burch/open3bet"))

from pushfold import hands  # noqa: E402

import floor3  # noqa: E402

N = len(hands.CLASSES)


def own_reach(sigma: np.ndarray, tree: floor3.Tree, seat: int) -> np.ndarray:
    """(nodes, 169): seat's own action-probability product along its own path to each node."""
    out = np.ones((len(tree.nodes), N))
    for nd in tree.nodes:
        if nd.seat == seat and nd.own_prev >= 0:
            prev = tree.nodes[nd.own_prev]
            k = prev.actions.index(nd.own_prev_action)
            out[nd.index] = out[nd.own_prev] * sigma[nd.own_prev, :, k]
    return out


def terminal_reach(tree: floor3.Tree, sigma: np.ndarray) -> np.ndarray:
    """(terminals,): probability each terminal is reached, under `sigma`."""
    r = {s: own_reach(sigma, tree, s) for s in range(tree.spot.n)}
    out = np.zeros(len(tree.terminals))
    for z in tree.terminals:
        p = 1.0
        for s in range(tree.spot.n):
            dec = z.decisions_of(s, tree.nodes)
            if not dec:
                continue
            last, act = dec[-1]
            k = tree.nodes[last].actions.index(act)
            p *= float(hands.PRIOR @ (r[s][last] * sigma[last, :, k]))
        out[z.index] = p
    return out


def kind_reach(tree: floor3.Tree, sigma: np.ndarray) -> dict[str, float]:
    pr = terminal_reach(tree, sigma)
    out = {}
    for z in tree.terminals:
        out[z.kind] = out.get(z.kind, 0.0) + float(pr[z.index])
    return out


def node_action_range(tree: floor3.Tree, sigma: np.ndarray, node_index: int) -> dict[str, float]:
    """PRIOR-weighted action frequencies at one decision node (a range as a chart shows it)."""
    nd = tree.nodes[node_index]
    return {floor3.ACTION_NAMES[a]: float(hands.PRIOR @ sigma[node_index, :, k])
            for k, a in enumerate(nd.actions)}
