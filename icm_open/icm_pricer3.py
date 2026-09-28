"""ICM pricer for the OPEN3BET Tier 1 tree ("open or jam": `floor3.build(..., tier1=True)`).

Generalises `pushfold/icm_pricer.py` the same way `pricer3.py` generalises `pushfold/pricer.py`:
a seat can act up to twice on one path (its own second decision, facing its own all-in-less-3bet
after opening), so a node's counterfactual value needs a *sequence*, not `node*2+action`, and the
seat's own future action probabilities ("later") must be carried and multiplied in separately
from the opponents' reach -- see `pricer3.py`'s module docstring, points 1-3, which apply here
unchanged. Everything else -- the ICM-specific math, `_layouts()`/`_pair()`, the group-by-target
batching of the six 3-way finish orders -- is `pushfold/icm_pricer.py`'s, reused by import rather
than re-derived, because that tensor algebra is exactly the part worth not re-deriving by hand.

Column reuse. The product columns this needs -- each opponent's full-path reach, and this seat's
own-later reach from a given decision onward -- are *exactly* the columns `pricer3.plan(tree)`
already builds and registers (same `_seq_ids`, same suffixes), because which columns are needed
is a fact about the action tree, not about chip EV vs ICM. So `plan()` below takes an existing
chip `pricer3.Plan` and reuses its `.prods`/`.one`/`.columns()` outright instead of rebuilding
them -- one shared, already-tested column space for both games, and `coach3` does not need to
know which one it is iterating (`SeatPlan.price` has the same signature either way).

Worth table. `_worth` (finish order -> ICM chips per seat) is johanson's `seqbr._worth`, called
through the `floor3.Tree -> seqbr.Game` adapter (`seqbr3.from_floor3`) that already backs
`seqbr3.Auditor`, so the same tested code computes the worth table here and in the slow oracle
this is meant to be checked against (`icm-pricer3-check.md`).

Tier 1 only: cap 3, no FLOP terminal ever reached, so no leaf model is consulted here.
"""

from __future__ import annotations

import dataclasses
import numpy as np

from pushfold import hands, icm, pricer
from pushfold.icm_pricer import _layouts, _pair   # ICM tensor algebra, reused, not re-derived

from . import floor3, pricer3, seqbr, seqbr3

N = len(hands.CLASSES)
FIXED, TWO, PAIR = 0, 1, 2
HERO = -1
_AXES = ((0, 1, 2), (1, 0, 2), (2, 0, 1))


@dataclasses.dataclass(frozen=True)
class SeatPlan:
    seat: int
    players: int
    nodes: np.ndarray
    slots: np.ndarray
    mask: np.ndarray
    width: int
    # simple terms: no 3-way finish order
    target: np.ndarray
    kind: np.ndarray
    coef: np.ndarray
    rival: np.ndarray
    second: np.ndarray
    mine: np.ndarray
    others: np.ndarray
    # 3-way finish-order terms, grouped by (target, layout, free) for the batched matrix product
    group_target: np.ndarray
    group_layout: np.ndarray
    group_free: np.ndarray
    group_mine: np.ndarray
    group_start: np.ndarray
    order_coef: np.ndarray
    order_y: np.ndarray
    order_z: np.ndarray
    order_others: np.ndarray

    def price(self, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return values(self, cols)


def plan(tree: floor3.Tree, payouts: icm.Payouts, chip_plan: pricer3.Plan | None = None
         ) -> pricer3.Plan:
    spot = tree.spot
    n = spot.n
    payouts.check(n)
    if any(len(z.live) > 3 for z in tree.terminals):
        raise ValueError("the Oddsmaker prices at most 3-way showdowns; lower the cap")
    chip_plan = chip_plan or pricer3.plan(tree)
    index_of = {ids: chip_plan.one + 1 + i for i, ids in enumerate(chip_plan.prods)}
    one = chip_plan.one

    def col_of(ids: tuple[int, ...]) -> int:
        ids = tuple(sorted(ids))
        if not ids:
            return one
        if len(ids) == 1:
            return ids[0]
        if ids not in index_of:
            raise KeyError(f"chip_plan never registered the product column {ids}; "
                            "it should have, since it needs the same opponent/own-later columns")
        return index_of[ids]

    worth = seqbr._worth(seqbr3.from_floor3(tree), payouts)

    seats = []
    for seat in range(n):
        own = tree.nodes_of(seat)
        nodes = np.array([nd.index for nd in own], dtype=np.int64)
        amax = tree.max_actions
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

        opp = [j for j in range(n) if j != seat]
        simple: list = []
        orders: list = []
        for z in tree.terminals:
            w = worth[z.index]
            mine_seqs = pricer3._seq_ids(tree, z, seat)
            col = {j: col_of(pricer3._seq_ids(tree, z, j)) for j in opp}
            points = ([(local_of_seq[s], col_of(mine_seqs[k + 1:]))
                       for k, s in enumerate(mine_seqs)] or [(-1, one)])

            def others(skip) -> list[int]:
                return [one if j in skip else col[j] for j in opp]

            alive = z.live
            if len(alive) == 1:
                for target, later in points:
                    simple.append((target, FIXED, w[alive][seat], one, one, later, others(())))
            elif len(alive) == 2:
                a, b = alive
                if seat in alive:
                    rival = b if seat == a else a
                    lose, win = w[(rival, seat)][seat], w[(seat, rival)][seat]
                    for target, later in points:
                        simple.append((target, FIXED, lose, one, one, later, others(())))
                        simple.append((target, TWO, win - lose, col[rival], one, later,
                                       others((rival,))))
                else:
                    b_wins, a_wins = w[(b, a)][seat], w[(a, b)][seat]
                    for target, later in points:
                        simple.append((target, FIXED, b_wins, one, one, later, others(())))
                        simple.append((target, PAIR, a_wins - b_wins, col[a], col[b], later,
                                       others(alive)))
            else:
                free_seat = seat if seat in alive else alive[0]
                free = HERO if seat in alive else col[free_seat]
                for order, row in w.items():
                    if row[seat] == 0.0:
                        continue
                    y, zz = (s for s in order if s != free_seat)
                    for target, later in points:
                        orders.append((target, order.index(free_seat), free, row[seat],
                                       col[y], col[zz], later, others(alive)))
        seats.append(_seat_plan(seat, n, nodes, slots, mask, width, simple, orders))
    return pricer3.Plan(tree, seats, chip_plan.prods, one)


def _seat_plan(seat: int, players: int, nodes: np.ndarray, slots: np.ndarray, mask: np.ndarray,
               width: int, simple: list, orders: list) -> SeatPlan:
    opp_width = players - 1
    simple = simple or [(-1, FIXED, 0.0, 0, 0, 0, [0] * opp_width)]
    t, kind, coef, rival, second, later, others = (list(x) for x in zip(*simple))
    orders = sorted(orders, key=lambda term: (term[0], term[1], term[2], term[6]))
    keys = [(term[0], term[1], term[2], term[6]) for term in orders]
    groups = sorted(set(keys))
    index = {g: i for i, g in enumerate(groups)}
    starts = np.searchsorted([index[k] for k in keys], np.arange(len(groups) + 1))
    return SeatPlan(
        seat, players, nodes, slots, mask, width,
        np.array(t), np.array(kind), np.array(coef, dtype=float),
        np.array(rival), np.array(second), np.array(later),
        np.array(others, dtype=np.int64).reshape(-1, opp_width),
        np.array([g[0] for g in groups], dtype=np.int64),
        np.array([g[1] for g in groups], dtype=np.int64),
        np.array([g[2] for g in groups], dtype=np.int64),
        np.array([g[3] for g in groups], dtype=np.int64),
        np.asarray(starts, dtype=np.int64),
        np.array([term[3] for term in orders], dtype=float),
        np.array([term[4] for term in orders], dtype=np.int64),
        np.array([term[5] for term in orders], dtype=np.int64),
        np.array([term[7] for term in orders], dtype=np.int64).reshape(len(orders), opp_width),
    )


def _three_way(p: SeatPlan, cols: np.ndarray, reach: np.ndarray) -> np.ndarray:
    """(169, groups): each group's ICM value per hand of the priced seat (or a constant, if the
    seat already folded -- see the `free` branch). Identical to `icm_pricer._three_way` except
    the `mine` (own-later reach) factor is applied per group at the end, once, since `later` is
    constant within a group (it depends only on `target`, which is part of the group key)."""
    w = p.order_coef * reach[p.order_others].prod(axis=1)
    y = cols[:, p.order_y] * w
    z = cols[:, p.order_z]
    weights = np.stack([y[:, a:b] @ z[:, a:b].T
                        for a, b in zip(p.group_start[:-1], p.group_start[1:])])
    out = np.zeros((N, len(weights)))
    for layout, tensor in enumerate(_layouts()):
        pick = p.group_layout == layout
        if pick.any():
            flat = weights[pick].reshape(-1, N * N).astype(np.float32)
            out[:, pick] = tensor @ flat.T
    free = p.group_free != HERO
    if free.any():
        summed = (hands.PRIOR[:, None] * cols[:, p.group_free[free]] * out[:, free]).sum(axis=0)
        out[:, free] = summed
    out *= cols[:, p.group_mine]
    return out


def values(p: SeatPlan, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Counterfactual ICM chips: (own nodes, 169, max actions) and the no-decision part (169,)."""
    reach = pricer.opponents(p.players) @ cols
    special = np.ones((N, len(p.kind)))
    two = p.kind == TWO
    if two.any():
        special[:, two] = pricer._two_way(p.players == 2) @ cols[:, p.rival[two]]
    pair = p.kind == PAIR
    if pair.any():
        a = hands.PRIOR[:, None] * cols[:, p.rival[pair]]
        special[:, pair] = (a * (_pair() @ cols[:, p.second[pair]])).sum(axis=0)
    v = p.coef * special * reach[:, p.others].prod(axis=2) * cols[:, p.mine]
    decided = p.target >= 0
    out = np.zeros((N, p.width))
    np.add.at(out.T, p.target[decided], v[:, decided].T)
    if len(p.group_target):
        group_v = _three_way(p, cols, reach[0])
        gdecided = p.group_target >= 0
        np.add.at(out.T, p.group_target[gdecided], group_v[:, gdecided].T)
    cfv = out[:, p.slots].transpose(1, 0, 2) * p.mask[:, None, :]
    no_decision = v[:, ~decided].sum(axis=1)
    if len(p.group_target):
        no_decision = no_decision + group_v[:, ~gdecided].sum(axis=1)
    return cfv, no_decision
