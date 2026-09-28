"""Chip-EV pricer for the OPEN3BET tree. Generalises `pushfold.pricer` in three ways.

1. SEQUENCES, NOT node*2+action. A node has 2-4 actions, so every (node, action) pair gets a
   global sequence id (`floor3.Node.seq`).

2. PRODUCT COLUMNS. `pushfold.pricer` multiplies in one strategy column per opponent, which is
   only right because each seat acts once. Here an opponent can act three times on one path, and
   with the independent-deal opponent model the probability that opponent j played the whole line
   is  sum_g PRIOR[g] prod_k sigma_j(g, a_k)  -- NOT the product of the per-action marginals. So
   the per-hand products are formed first (`columns`), then the opponent model is applied.

3. OWN REACH. The counterfactual value of (node, action) must include this seat's own action
   probabilities strictly *below* that node and exclude those above it. `mine` carries the column
   of that own-later product. In push/fold it is always the ones column, which is why
   `pushfold.pricer` does not have it.

The same three points are why `pushfold.coach`'s average and `pushfold.auditor`'s best response
are both wrong on this tree without change; see `NOTES.md`.

For n >= 3 seats the opponent model is PRIOR-independent, so a non-showdown opponent's reach is a
scalar, not a 169-vector. This pricer exploits that (`_reach_products`); `pushfold.pricer` forms
the full (169, columns) matrix instead. Same numbers, less work.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from pushfold import hands, pricer
from pushfold.spot import Spot

import cashier3
import floor3

N = len(hands.CLASSES)
FIXED, TWO, THREE, SIDE = pricer.FIXED, pricer.TWO, pricer.THREE, pricer.SIDE
CHUNK = 512          # terms per 3-way batch: caps the (169,169,chunk) temporary at ~60 MB


@dataclasses.dataclass(frozen=True)
class SeatPlan:
    seat: int
    players: int
    nodes: np.ndarray        # global node indices where this seat acts
    slots: np.ndarray        # (own nodes, max actions) local column of each action, 0 where illegal
    mask: np.ndarray         # (own nodes, max actions) legal actions
    width: int               # local columns = sum of action counts over this seat's nodes
    target: np.ndarray       # per term: local column, -1 = this seat never acted on that path
    kind: np.ndarray
    coef: np.ndarray
    rival: np.ndarray
    third: np.ndarray
    mine: np.ndarray         # per term: column of this seat's own-later product
    others: np.ndarray       # (terms, n-1) columns of the opponents' line products
    zid: np.ndarray          # per term: which terminal it came from (`terminal_values` key)
    rank: np.ndarray         # per term: 0 for this seat's FIRST decision on that path (or the
                              # sole "no decision" row); >0 for a later decision on the same
                              # path. `terminal_values` keeps only rank == 0: once `mine` is
                              # dropped, a later decision's row is the identical settlement term
                              # again, and summing both would double the terminal's raw value.

    def price(self, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return values(self, cols)


@dataclasses.dataclass(frozen=True)
class Plan:
    tree: floor3.Tree
    seats: list[SeatPlan]
    prods: tuple[tuple[int, ...], ...]   # product columns, in order after the ones column
    one: int

    def columns(self, sigma: np.ndarray) -> np.ndarray:
        return columns(self.tree, sigma, self.prods)


def _seq_ids(tree: floor3.Tree, z: floor3.Terminal, seat: int) -> tuple[int, ...]:
    return tuple(tree.nodes[i].seq(a) for i, a in z.path if tree.nodes[i].seat == seat)


def plan(tree: floor3.Tree, leaf: cashier3.Leaf = cashier3.checkdown) -> Plan:
    spot: Spot = tree.spot
    n = spot.n
    one = tree.sequences
    prods: dict[tuple[int, ...], int] = {}

    def col_of(ids) -> int:
        ids = tuple(sorted(ids))
        if not ids:
            return one
        if len(ids) == 1:
            return ids[0]
        if ids not in prods:
            prods[ids] = one + 1 + len(prods)
        return prods[ids]

    mixes = [cashier3.price_terminal(spot, z, leaf) for z in tree.terminals]
    for mix in mixes:
        for _, s in mix:
            if any(len(layer.eligible) > 3 for layer in s.layers):
                raise ValueError("the Oddsmaker prices at most 3-way showdowns; lower the cap")

    seats: list[SeatPlan] = []
    for seat in range(n):
        own = tree.nodes_of(seat)
        nodes = np.array([nd.index for nd in own], dtype=np.int64)
        amax = tree.max_actions   # one global action width, so sigma is one array
        slots = np.zeros((len(own), amax), dtype=np.int64)
        mask = np.zeros((len(own), amax), dtype=bool)
        local_of_seq: dict[int, int] = {}
        width = 0
        for row, nd in enumerate(own):
            for k, a in enumerate(nd.actions):
                slots[row, k] = width
                mask[row, k] = True
                local_of_seq[nd.seq(a)] = width
                width += 1

        rows = []
        for z, mix in zip(tree.terminals, mixes):
            mine_seqs = _seq_ids(tree, z, seat)
            opp = [j for j in range(n) if j != seat]
            col = {j: col_of(_seq_ids(tree, z, j)) for j in opp}
            # one row per own decision on this path; targets get the own-later product
            points = [(local_of_seq[s], col_of(mine_seqs[k + 1:]))
                      for k, s in enumerate(mine_seqs)] or [(-1, one)]
            for w, s in mix:
                terms = [(FIXED, w * s.fixed[seat], one, one, ())]
                for layer in s.layers:
                    if seat not in layer.eligible:
                        continue      # chip EV: a folded seat does not care who wins
                    rivals = [j for j in layer.eligible if j != seat]
                    if len(rivals) == 2:
                        terms.append((THREE, w * layer.amount, col[rivals[0]], col[rivals[1]], rivals))
                    elif len(z.live) == 3:
                        dead = [j for j in z.live if j not in layer.eligible][0]
                        terms.append((SIDE, w * layer.amount, col[rivals[0]], col[dead], [rivals[0], dead]))
                    else:
                        terms.append((TWO, w * layer.amount, col[rivals[0]], one, rivals))
                for rank, (target, later) in enumerate(points):
                    for kind, coef, k, l, skip in terms:
                        if coef == 0.0:
                            continue
                        rows.append((target, kind, coef, k, l, later,
                                     [one if j in skip else col[j] for j in opp], z.index, rank))
        t, kind, coef, k, l, later, others, zid, rank = zip(*rows)
        seats.append(SeatPlan(seat, n, nodes, slots, mask, width, np.array(t), np.array(kind),
                              np.array(coef, dtype=float), np.array(k), np.array(l),
                              np.array(later), np.array(others, dtype=np.int64),
                              np.array(zid), np.array(rank)))
    ordered = tuple(k for k, _ in sorted(prods.items(), key=lambda kv: kv[1]))
    return Plan(tree, seats, ordered, one)


def columns(tree: floor3.Tree, sigma: np.ndarray, prods) -> np.ndarray:
    """(nodes, 169, A) padded strategy -> (169, sequences + 1 + products) columns.

    Column `s` is sigma at the (node, action) with sequence id s; then a ones column; then one
    column per multi-decision line, the per-hand product of its actions.
    """
    flat = np.ones((N, tree.sequences + 1 + len(prods)))
    for nd in tree.nodes:
        for k, _ in enumerate(nd.actions):
            flat[:, nd.base + k] = sigma[nd.index, :, k]
    for i, ids in enumerate(prods):
        flat[:, tree.sequences + 1 + i] = flat[:, list(ids)].prod(axis=1)
    return flat


def _reach_products(p: SeatPlan, cols: np.ndarray) -> np.ndarray:
    """Product of the opponents' line reaches, per term. (169, terms), or (1, terms) if constant."""
    return _reach_from(p.others, p.players, cols)


def _reach_from(others: np.ndarray, players: int, cols: np.ndarray) -> np.ndarray:
    if players == 2:
        return (hands.M @ cols)[:, others].prod(axis=2)
    scalar = hands.PRIOR @ cols                      # independent deals: reach is hand-independent
    return scalar[others].prod(axis=1)[None, :]


def values(p: SeatPlan, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Counterfactual chips: (own nodes, 169, max actions) and the no-decision part (169,)."""
    special = np.ones((N, len(p.kind)))
    two = p.kind == TWO
    if two.any():
        special[:, two] = pricer._two_way(p.players == 2) @ cols[:, p.rival[two]]
    for kind, tensor in ((THREE, 0), (SIDE, 1)):
        pick = np.flatnonzero(p.kind == kind)
        if not len(pick):
            continue
        flat = pricer._three_way()[tensor]
        for lo in range(0, len(pick), CHUNK):
            sl = pick[lo:lo + CHUNK]
            inner = (flat @ cols[:, p.third[sl]].astype(np.float32)).reshape(N, N, -1)
            special[:, sl] = np.einsum("hgm,gm->hm", inner, cols[:, p.rival[sl]].astype(np.float32))
    v = p.coef * special * _reach_products(p, cols) * cols[:, p.mine]
    decided = p.target >= 0
    out = np.zeros((N, p.width))
    np.add.at(out.T, p.target[decided], v[:, decided].T)
    cfv = out[:, p.slots].transpose(1, 0, 2) * p.mask[:, None, :]
    return cfv, v[:, ~decided].sum(axis=1)


def _special(kind: np.ndarray, rival: np.ndarray, third: np.ndarray, players: int,
             cols: np.ndarray) -> np.ndarray:
    """The equity factor shared by `values` and `terminal_values`: batched across every row at
    once (one big matmul/einsum per chunk, not one per terminal) -- this is the fix for
    `seqbr.chip_values`/`icm_values` looping per terminal (`tier1-audit-speed.md`)."""
    special = np.ones((N, len(kind)))
    two = kind == TWO
    if two.any():
        special[:, two] = pricer._two_way(players == 2) @ cols[:, rival[two]]
    for k, tensor in ((THREE, 0), (SIDE, 1)):
        pick = np.flatnonzero(kind == k)
        if not len(pick):
            continue
        flat = pricer._three_way()[tensor]
        for lo in range(0, len(pick), CHUNK):
            sl = pick[lo:lo + CHUNK]
            inner = (flat @ cols[:, third[sl]].astype(np.float32)).reshape(N, N, -1)
            special[:, sl] = np.einsum("hgm,gm->hm", inner, cols[:, rival[sl]].astype(np.float32))
    return special


def terminal_values(p: SeatPlan, cols: np.ndarray, terminals: int) -> np.ndarray:
    """(169, terminals): raw chip value to `p.seat`, every OTHER seat's actual reach folded in,
    `p.seat`'s own reach (past and future) entirely excluded -- the quantity a sequential best
    response needs at the leaves, before backward induction up the tree (`seqbr._walk`, cheap:
    37ms for 2 x 9 seats on the 494-node n=9 Tier 1 tree, measured -- the terminal loop in
    `seqbr.chip_values` is the part that was slow, 8.1s on the same tree, because it re-touches
    the full (169, 169, 169) equity table once per terminal in a Python loop instead of batching).
    """
    rank0 = p.rank == 0
    special = _special(p.kind[rank0], p.rival[rank0], p.third[rank0], p.players, cols)
    v = p.coef[rank0] * special * _reach_from(p.others[rank0], p.players, cols)
    out = np.zeros((N, terminals))
    np.add.at(out.T, p.zid[rank0], v.T)
    return out


def all_terminal_values(plan: Plan, sigma: np.ndarray) -> np.ndarray:
    """(seats, 169, terminals): `terminal_values` for every seat, in `plan.tree.terminals`
    order -- matches `seqbr3.from_floor3(tree)`'s ending order, so this can be dropped straight
    into `seqbr.audit(game, sigma, payouts, U=...)` as `U[seat]` for chip EV."""
    cols = plan.columns(sigma)
    terminals = len(plan.tree.terminals)
    return np.stack([terminal_values(p, cols, terminals) for p in plan.seats])
