"""Prices every ending for one seat: the Cashier's payouts times the Oddsmaker's tables.

For a seat holding class h, opponent j holds class g with chance O[h, g], and the chance
that j took the action it took is (O @ sigma_j)[h]. A whole ending costs one product of
those vectors. Showdowns multiply in e2 (heads-up) or the 3-way tensors.

O is the opponent model:
* heads-up: O = M, exact blockers from W. Both seats share one joint deal, so EVs sum to 0.
* 3+ players: O[h, g] = PRIOR[g], opponents dealt independently. Conditioning every seat
  on its own blockers gives each seat a different picture of the deal: EVs stopped summing
  to 0 (+0.21bb at 9-handed) and drifted further from exact deals than the independent
  model (max seat error 0.042 vs 0.014bb, 400k real deals). Card removal still lives
  inside e2/eq3/pw, which are averaged over compatible combos.

Everything is a matrix product over the 169 classes, so no hand is ever dealt.
"""

from __future__ import annotations

import dataclasses
import functools

import numpy as np

from pushfold import cashier, hands, oddsmaker
from pushfold.floor import Tree

N = len(hands.CLASSES)
FIXED, TWO, THREE, SIDE = 0, 1, 2, 3  # what gets multiplied in: nothing, e2, eq3, pw


def opponents(n: int) -> np.ndarray:
    """O[h, g]: chance an opponent holds g when I hold h, at an n-handed table."""
    return hands.M if n == 2 else np.tile(hands.PRIOR, (N, 1))


@functools.lru_cache(maxsize=2)
def _two_way(n_is_two: bool) -> np.ndarray:
    return opponents(2 if n_is_two else 3) * oddsmaker.two_way()


@functools.lru_cache(maxsize=1)
def _three_way() -> tuple[np.ndarray, np.ndarray]:
    """PRIOR[g] PRIOR[k] eq3[h,g,k] and the same for pw, flattened for one matrix product."""
    t = oddsmaker.three_way()
    both = hands.PRIOR[None, :, None] * hands.PRIOR[None, None, :]
    return (both * t.eq3).reshape(N * N, N), (both * t.pw).reshape(N * N, N)


@dataclasses.dataclass(frozen=True)
class SeatPlan:
    seat: int
    players: int
    nodes: np.ndarray    # global node indices where this seat acts
    target: np.ndarray   # per term: column node_local*2+action in the seat's values, -1 = no decision
    kind: np.ndarray     # per term: FIXED, TWO, THREE or SIDE
    coef: np.ndarray     # per term: chips
    rival: np.ndarray    # per term: strategy column of the opponent in the showdown (k)
    third: np.ndarray    # per term: strategy column of the third hand (l)
    others: np.ndarray   # (terms, n-1): strategy columns whose reach multiplies in; ONE = skip

    def price(self, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return values(self, cols)


def _column(terminal, seat) -> int:
    return terminal.nodes[seat] * 2 + terminal.actions[seat]


def plan(tree: Tree) -> list[SeatPlan]:
    if any(len(z.jammers) > 3 for z in tree.terminals):
        raise ValueError("the Oddsmaker prices at most 3-way showdowns; build the tree with max_allin <= 3")
    one = 2 * len(tree.nodes)          # index of an all-ones column
    plans = []
    for seat in range(tree.spot.n):
        nodes = np.array([n.index for n in tree.nodes_of(seat)], dtype=np.int64)
        local = {g: i for i, g in enumerate(nodes)}
        rows = []
        for z in tree.terminals:
            # node -1: the seat made no decision (never got to act, or all-in by posting)
            target = -1 if z.nodes[seat] < 0 else local[z.nodes[seat]] * 2 + z.actions[seat]
            opp = [j for j in range(tree.spot.n) if j != seat]
            col = {j: (one if z.nodes[j] < 0 else _column(z, j)) for j in opp}
            s = cashier.settle(tree.spot, z.jammers)
            terms = [(FIXED, s.fixed[seat], one, one, ())]
            for layer in s.layers:
                if seat not in layer.eligible:
                    continue
                rivals = [j for j in layer.eligible if j != seat]
                if len(rivals) == 2:
                    terms.append((THREE, layer.amount, col[rivals[0]], col[rivals[1]], rivals))
                elif len(z.jammers) == 3:
                    dead = [j for j in z.jammers if j not in layer.eligible][0]
                    terms.append((SIDE, layer.amount, col[rivals[0]], col[dead], [rivals[0], dead]))
                else:
                    terms.append((TWO, layer.amount, col[rivals[0]], one, rivals))
            for kind, coef, k, l, skip in terms:
                rows.append((target, kind, coef, k, l,
                             [one if j in skip else col[j] for j in opp]))
        t, kind, coef, k, l, others = zip(*rows)
        plans.append(SeatPlan(seat, tree.spot.n, nodes, np.array(t), np.array(kind), np.array(coef),
                              np.array(k), np.array(l), np.array(others, dtype=np.int64)))
    return plans


def columns(sigma: np.ndarray) -> np.ndarray:
    """(nodes, 169, 2) strategy -> (169, 2*nodes + 1) columns plus a ones column."""
    flat = sigma.transpose(1, 0, 2).reshape(N, -1)
    return np.hstack([flat, np.ones((N, 1))])


def values(p: SeatPlan, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Counterfactual chips for one seat: (its nodes, 169, 2) and the no-decision part (169,)."""
    reach = opponents(p.players) @ cols
    special = np.ones((N, len(p.kind)))
    two = p.kind == TWO
    special[:, two] = (_two_way(p.players == 2) @ cols[:, p.rival[two]])
    for kind, tensor in ((THREE, 0), (SIDE, 1)):
        pick = p.kind == kind
        if pick.any():
            flat = _three_way()[tensor]
            inner = (flat @ cols[:, p.third[pick]]).reshape(N, N, -1)
            special[:, pick] = np.einsum("hgm,gm->hm", inner, cols[:, p.rival[pick]])
    v = p.coef * special * reach[:, p.others].prod(axis=2)
    decided = p.target >= 0
    out = np.zeros((N, 2 * len(p.nodes)))
    np.add.at(out.T, p.target[decided], v[:, decided].T)
    return out.reshape(N, len(p.nodes), 2).transpose(1, 0, 2), v[:, ~decided].sum(axis=1)
