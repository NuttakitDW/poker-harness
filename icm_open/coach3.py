"""CFR / CFR+ / DCFR over the OPEN3BET tree. Same three methods as `pushfold.coach`, two fixes.

RAGGED ACTIONS. Regrets and the average are (nodes, 169, max_actions) with a legality mask;
illegal actions are held at zero regret and zero probability.

AVERAGING. `pushfold.coach` accumulates `total[nodes] += weight * sigma[nodes]`, the behaviour
probabilities. That equals sequence-form averaging only because each seat acts at most once on a
path, so its own reach to any of its nodes is 1. Here a seat acts up to three times, and the
average of behaviour strategies is not the strategy whose sequence weights are the average -- the
classic point in Zinkevich et al., *Regret minimization in games with incomplete information*
(NIPS 2007). So the average is accumulated with this seat's own reach:

    total[nodes] += weight * pi_i^sigma_t(node) * sigma_t(node)

and normalised at the end. Own reach is computed from the same sigma that produced the values,
before this seat's update, because seats are updated one at a time (alternating, Gauss-Seidel,
as in `pushfold.coach`; see Burch, Moravcik, Schmid, *Revisiting CFR+ and Alternating Updates*,
JAIR 64, 2019 for why the update order matters to the bound).

NOT A SOLVER YET. There is no stop rule here, because a stop rule needs an exploitability number
and `pushfold.auditor`'s one-action best response is not a best response on this tree (a seat's
best action at its first decision depends on what it would do at its second). That is johanson's
piece. `run()` below does a fixed number of iterations, for cost measurement only.
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np

from pushfold import hands

from . import floor3, pricer3

METHODS = ("cfr", "cfr+", "dcfr")
ALPHA, BETA, GAMMA = 1.5, 0.0, 2.0
N = len(hands.CLASSES)


@dataclasses.dataclass
class State:
    tree: floor3.Tree
    plan: pricer3.Plan
    mask: np.ndarray       # (nodes, A)
    regret: np.ndarray     # (nodes, 169, A)
    total: np.ndarray
    sigma: np.ndarray
    t: int = 0

    @property
    def bytes(self) -> int:
        return sum(a.nbytes for a in (self.regret, self.total, self.sigma))

    def average(self) -> np.ndarray:
        s = self.total.sum(axis=2, keepdims=True)
        return np.where(s > 0, self.total / np.where(s > 0, s, 1.0), self.uniform())

    def uniform(self) -> np.ndarray:
        k = self.mask.sum(axis=1, keepdims=True)[:, None, :]
        return self.mask[:, None, :] / np.maximum(k, 1)


def _match(regret: np.ndarray, mask: np.ndarray) -> np.ndarray:
    pos = np.maximum(regret, 0.0) * mask[:, None, :]
    tot = pos.sum(axis=-1, keepdims=True)
    k = np.maximum(mask.sum(axis=1, keepdims=True), 1)[:, None, :]
    return np.where(tot > 0, pos / np.where(tot > 0, tot, 1.0), mask[:, None, :] / k)


def start(tree: floor3.Tree, plan: pricer3.Plan) -> State:
    a = tree.max_actions
    mask = np.zeros((len(tree.nodes), a), dtype=bool)
    for nd in tree.nodes:
        mask[nd.index, :len(nd.actions)] = True
    shape = (len(tree.nodes), N, a)
    st = State(tree, plan, mask, np.zeros(shape), np.zeros(shape), np.zeros(shape))
    st.sigma = st.uniform() * np.ones((1, N, 1))
    return st


def own_reach(st: State, seat: int) -> np.ndarray:
    """pi_i^sigma(node) for every node of `seat`: (its nodes, 169). Nodes are in DFS order."""
    reach = np.ones((len(st.tree.nodes), N))
    for nd in st.tree.nodes:
        if nd.seat == seat and nd.own_prev >= 0:
            prev = st.tree.nodes[nd.own_prev]
            k = prev.actions.index(nd.own_prev_action)
            reach[nd.index] = reach[nd.own_prev] * st.sigma[nd.own_prev, :, k]
    return reach


def iterate(st: State, method: str = "cfr+") -> None:
    st.t += 1
    t = st.t
    cols = st.plan.columns(st.sigma)
    for p in st.plan.seats:
        if not len(p.nodes):
            continue
        cfv, _ = p.price(cols)
        m = st.mask[p.nodes]
        mine = st.sigma[p.nodes]
        gain = (cfv - (mine * cfv).sum(axis=2, keepdims=True)) * m[:, None, :]
        r = st.regret[p.nodes]
        if method == "cfr+":
            r = np.maximum(r + gain, 0.0)
        elif method == "dcfr":
            r = np.where(r > 0, r * t**ALPHA / (t**ALPHA + 1), r * t**BETA / (t**BETA + 1)) + gain
        else:
            r = r + gain
        st.regret[p.nodes] = r
        weight = {"cfr": 1.0, "cfr+": float(t)}.get(method)
        if weight is None:
            st.total[p.nodes] *= ((t - 1) / t) ** GAMMA
            weight = 1.0
        reach = own_reach(st, p.seat)[p.nodes]          # sigma before this seat's update
        st.total[p.nodes] += weight * reach[:, :, None] * mine
        st.sigma[p.nodes] = _match(r, m)


def run(tree: floor3.Tree, iters: int, method: str = "cfr+",
        leaf=None) -> tuple[State, float, float]:
    """Returns (state, seconds to plan, seconds per iteration). No stop rule: cost only."""
    t0 = time.perf_counter()
    plan = pricer3.plan(tree) if leaf is None else pricer3.plan(tree, leaf)
    planned = time.perf_counter() - t0
    st = start(tree, plan)
    iterate(st, method)                                  # warm the caches
    t0 = time.perf_counter()
    for _ in range(iters):
        iterate(st, method)
    return st, planned, (time.perf_counter() - t0) / iters
