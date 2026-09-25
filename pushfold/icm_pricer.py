"""The ICM Pricer: prices every ending in prize money instead of chips.

Chip EV is linear in chips, so the Pricer can price a pot as its size x equity. ICM is not:
it has to know exactly how a showdown turned out. For each ending, every finish order of the
players still in is sent to the Cashier (final stacks) and then to ICM (value per seat).
A seat's value is then the sum over orders of chance x value:

* nobody left to fight:  one outcome, a fixed value.
* heads-up a vs b:       value(b wins) + (value(a wins) - value(b wins)) x P(a beats b), from e2.
                         A seat that folded is paid too: busting someone moves it up the ladder.
* 3-way:                 six orders, each with P(first, second, third) from Oddsmaker.orders().

Opponent model as in the Pricer: exact blockers heads-up, independent deals at 3+ players.
Values are ICM chips (see icm.py) minus the value of the stacks before the hand.

3-way terms are the costly part: each is a (169 x 169^2) tensor against two strategy columns.
Terms that land in the same place are summed into one 169x169 weight matrix first, so each
place costs one matrix product however many orders feed it.
"""

from __future__ import annotations

import dataclasses
import functools
import itertools

import numpy as np

from pushfold import cashier, hands, icm, oddsmaker, pricer
from pushfold.floor import Terminal, Tree

N = len(hands.CLASSES)
FIXED, TWO, PAIR = 0, 1, 2   # times nothing, e2 against one rival, P(a beats b) for a bystander
HERO = -1                    # 3-way group kept per hand of the seat being priced
_AXES = ((0, 1, 2), (1, 0, 2), (2, 0, 1))   # the free hand's place first, then the other two in order


@dataclasses.dataclass(frozen=True)
class SeatPlan:
    seat: int
    players: int
    nodes: np.ndarray        # global node indices where this seat acts
    # Terms without a 3-way showdown. target: output column; the last column = no decision.
    target: np.ndarray
    kind: np.ndarray         # FIXED, TWO or PAIR
    coef: np.ndarray         # ICM chips
    rival: np.ndarray        # TWO: the opponent's strategy column. PAIR: player a
    second: np.ndarray       # PAIR: player b
    others: np.ndarray       # (terms, n-1) columns whose reach multiplies in
    # 3-way finish orders, sorted by group.
    group_target: np.ndarray
    group_layout: np.ndarray  # which finishing place the free hand holds: 0, 1 or 2
    group_free: np.ndarray    # HERO, or the column of the player summed over (a bystander's view)
    group_start: np.ndarray   # (groups + 1) term boundaries
    order_coef: np.ndarray
    order_y: np.ndarray       # the other two places, in finishing order
    order_z: np.ndarray
    order_others: np.ndarray

    def price(self, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return values(self, cols)


def plans_for(tree: Tree, payouts: icm.Payouts | None) -> list:
    """Chip EV plans without payouts, ICM plans with them."""
    return pricer.plan(tree) if payouts is None else plan(tree, payouts)


@functools.lru_cache(maxsize=1)
def _layouts() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """orders() with the free hand's place moved first, opponents weighted by PRIOR, (169, 169^2)."""
    o = oddsmaker.orders()
    both = (hands.PRIOR[:, None] * hands.PRIOR[None, :]).astype(np.float32)
    return tuple(np.ascontiguousarray((o.transpose(axes) * both[None]).reshape(N, N * N))
                 for axes in _AXES)


@functools.lru_cache(maxsize=1)
def _pair() -> np.ndarray:
    """e2[g, k] x PRIOR[k]: a bystander's P(a beats b) = (PRIOR c_a) . (this @ c_b)."""
    return oddsmaker.two_way() * hands.PRIOR[None, :]


def _worth(tree: Tree, payouts: icm.Payouts) -> list[dict[tuple[int, ...], np.ndarray]]:
    """Per terminal: finish order of the players still in -> ICM chips won or lost per seat."""
    spot = tree.spot
    keys, finals = [], []
    for z in tree.terminals:
        settlement = cashier.settle(spot, z.jammers)
        for order in itertools.permutations(z.alive):
            net = settlement.net_for({s: place + 1 for place, s in enumerate(order)})
            keys.append((z.index, order))
            finals.append(np.array(spot.stacks) + net)
    before = icm.value(np.array([spot.stacks]), spot.stacks, payouts)[0]
    worth = icm.value(np.array(finals), spot.stacks, payouts) - before
    out: list[dict] = [{} for _ in tree.terminals]
    for (index, order), row in zip(keys, worth):
        out[index][order] = row
    return out


def _terms(z: Terminal, seat: int, worth: dict, col: dict, opp: list[int], target: int,
           one: int) -> tuple[list, list]:
    """(simple terms, 3-way terms) for one seat at one terminal."""
    def others(skip) -> list[int]:
        return [one if j in skip else col[j] for j in opp]

    alive = z.alive
    simple, orders = [], []
    if len(alive) == 1:
        simple.append((target, FIXED, worth[alive][seat], one, one, others(())))
    elif len(alive) == 2:
        a, b = alive
        if seat in alive:
            rival = b if seat == a else a
            lose, win = worth[(rival, seat)][seat], worth[(seat, rival)][seat]
            simple.append((target, FIXED, lose, one, one, others(())))
            simple.append((target, TWO, win - lose, col[rival], one, others((rival,))))
        else:
            b_wins, a_wins = worth[(b, a)][seat], worth[(a, b)][seat]
            simple.append((target, FIXED, b_wins, one, one, others(())))
            simple.append((target, PAIR, a_wins - b_wins, col[a], col[b], others(alive)))
    else:
        free_seat = seat if seat in alive else alive[0]
        free = HERO if seat in alive else col[free_seat]
        for order, row in worth.items():
            if row[seat] == 0.0:   # only saves work: a zero term adds nothing
                continue
            y, z_ = (s for s in order if s != free_seat)
            orders.append(((target, order.index(free_seat), free), row[seat], col[y], col[z_],
                           others(alive)))
    return simple, orders


def plan(tree: Tree, payouts: icm.Payouts) -> list[SeatPlan]:
    spot = tree.spot
    payouts.check(spot.n)
    if any(len(z.jammers) > 3 for z in tree.terminals):
        raise ValueError("the Oddsmaker prices at most 3-way showdowns; build the tree with max_allin <= 3")
    worth = _worth(tree, payouts)
    one = 2 * len(tree.nodes)
    plans = []
    for seat in range(spot.n):
        nodes = np.array([n.index for n in tree.nodes_of(seat)], dtype=np.int64)
        local = {g: i for i, g in enumerate(nodes)}
        undecided = 2 * len(nodes)
        opp = [j for j in range(spot.n) if j != seat]
        simple, orders = [], []
        for z in tree.terminals:
            target = undecided if z.nodes[seat] < 0 else local[z.nodes[seat]] * 2 + z.actions[seat]
            col = {j: (one if z.nodes[j] < 0 else z.nodes[j] * 2 + z.actions[j]) for j in opp}
            s, o = _terms(z, seat, worth[z.index], col, opp, target, one)
            simple += s
            orders += o
        plans.append(_seat_plan(seat, spot.n, nodes, simple, orders))
    return plans


def _seat_plan(seat: int, players: int, nodes: np.ndarray, simple: list, orders: list) -> SeatPlan:
    width = players - 1
    simple = simple or [(0, FIXED, 0.0, 0, 0, [0] * width)]
    t, kind, coef, rival, second, others = (np.array(x) for x in zip(*simple))
    orders = sorted(orders, key=lambda term: term[0])
    keys = [term[0] for term in orders]
    groups = sorted(set(keys))
    index = {g: i for i, g in enumerate(groups)}
    starts = np.searchsorted([index[k] for k in keys], np.arange(len(groups) + 1))
    return SeatPlan(
        seat, players, nodes, t, kind, coef, rival, second, others.astype(np.int64).reshape(-1, width),
        np.array([g[0] for g in groups], dtype=np.int64),
        np.array([g[1] for g in groups], dtype=np.int64),
        np.array([g[2] for g in groups], dtype=np.int64),
        np.asarray(starts, dtype=np.int64),
        np.array([term[1] for term in orders], dtype=float),
        np.array([term[2] for term in orders], dtype=np.int64),
        np.array([term[3] for term in orders], dtype=np.int64),
        np.array([term[4] for term in orders], dtype=np.int64).reshape(len(orders), width),
    )


def _three_way(p: SeatPlan, cols: np.ndarray, reach: np.ndarray) -> np.ndarray:
    """(169, groups): each group's value per hand of the seat (or a bystander's scalar)."""
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
    return out


def values(p: SeatPlan, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Counterfactual ICM chips for one seat: (its nodes, 169, 2) and the no-decision part (169,)."""
    reach = pricer.opponents(p.players) @ cols
    special = np.ones((N, len(p.kind)))
    two = p.kind == TWO
    special[:, two] = pricer._two_way(p.players == 2) @ cols[:, p.rival[two]]
    pair = p.kind == PAIR
    if pair.any():
        a = hands.PRIOR[:, None] * cols[:, p.rival[pair]]
        special[:, pair] = (a * (_pair() @ cols[:, p.second[pair]])).sum(axis=0)
    out = np.zeros((N, 2 * len(p.nodes) + 1))
    v = p.coef * special * reach[:, p.others].prod(axis=2)
    np.add.at(out.T, p.target, v.T)
    if len(p.group_target):
        np.add.at(out.T, p.group_target, _three_way(p, cols, reach[0]).T)
    cfv = out[:, :-1].reshape(N, len(p.nodes), 2).transpose(1, 0, 2)
    return cfv, out[:, -1]
