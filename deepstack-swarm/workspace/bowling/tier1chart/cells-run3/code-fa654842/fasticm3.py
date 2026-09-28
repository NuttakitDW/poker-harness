"""Batched ICM auditor for the OPEN3BET Tier 1 tree -- the ICM counterpart of `seqbr3.FastAuditor`.

The slow oracle (`seqbr3.Auditor` -> `seqbr.icm_values`) loops over terminals x seats x finish
orders in Python and re-touches the full (169,169,169) order tensor once per term (via
`np.einsum("hgk,g,k->h", ...)`). At n=9 that is 9 seats x 294 three-way terminals x 6 orders =
~16k einsum calls, 90.6s per audit (`burch-tier1-solve.md`). This module is the batching recipe
in `solve3.py`'s docstring, in code:

1. REGROUP BY TERMINAL, NOT BY TARGET. `icm_pricer3` groups its 3-way terms by (own-decision
   target, layout, free) because `coach3` needs one counterfactual value column per (node,
   action). The auditor needs one value column per *terminal*, so the terms are grouped by
   (terminal, layout, free) instead -- and the `points` loop over a seat's own decisions
   disappears (there is exactly one row per (terminal, seat, order)).
2. DROP THE OWN-LATER FACTOR. `icm_pricer3` multiplies each term by `cols[:, mine]`, this seat's
   own-later reach, because a counterfactual value excludes the seat's own actions above the
   node but includes the ones below. A terminal value is counterfactual in *both* directions, so
   `mine` is the ones column and the factor is dropped (`pricer3.terminal_values` does the same
   for chip EV).
3. KEEP rank == 0. `pricer3` emits one row per own decision on a path and keeps only `rank == 0`
   for terminal values; with `mine` dropped, every rank's row is the identical settlement term
   again, so keeping more than one would multiply a terminal's value by the number of decisions.

What that leaves is a per-(terminal, seat) sum of terms whose only hand-dependent part is
    C[l](y, x)[h] = sum_{g,k} orders_axes[l][h,g,k] PRIOR[g] y[g] PRIOR[k] x[k]
for two strategy columns y, x. y and x are *column indices into the shared `pricer3` column
space*, so C depends on nothing but (l, y, x) -- not on the terminal, not on the seat. That is
the whole speedup: `_CKeys` computes each distinct C once (a batched tensor contraction, at most
a few hundred of them), and every term anywhere in the tree is then a gather, a scalar multiply
and a scatter-add (`np.add.at`) into its terminal's column.

Column space, worth table and the walk are all shared with the chip path: columns come from
`pricer3.plan(tree).columns(sigma)`, the worth table from `seqbr._worth(game, payouts)`, and the
backward induction from `seqbr.audit(..., U=...)` -- the same code `seqbr3.Auditor` uses, so
agreement is a statement about the terminal values only.

Tier 1 only, like `seqbr3`: every ending is ALLFOLD/UNCONTESTED/SHOWDOWN, one settlement
component each.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import numpy as np

from pushfold import hands, icm, pricer
from pushfold.icm_pricer import _layouts, _pair

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "johanson"))
import seqbr  # noqa: E402

import floor3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402

N = len(hands.CLASSES)
FIXED, TWO, PAIR = 0, 1, 2
HERO = -1                 # the free hand is the priced seat's own hand: C is a 169-vector
CHUNK = 256               # keys per tensor batch: caps the (169, 169, CHUNK) temporary at ~37 MB


@dataclasses.dataclass(frozen=True)
class SeatPlan:
    seat: int
    players: int
    # terms with no 3-way finish order. Kind is FIXED / TWO / PAIR, as in `icm_pricer3`.
    s_zid: np.ndarray        # which terminal each row feeds
    s_kind: np.ndarray
    s_coef: np.ndarray
    s_rival: np.ndarray
    s_second: np.ndarray
    s_others: np.ndarray     # (rows, players-1) columns whose reach multiplies in
    # 3-way finish orders, one row per (terminal, order)
    t_zid: np.ndarray
    t_coef: np.ndarray
    t_others: np.ndarray     # (rows, players-1)
    t_key: np.ndarray        # row of `Plan.keys` this term reads C from


@dataclasses.dataclass(frozen=True)
class Plan:
    tree: floor3.Tree
    chip_plan: pricer3.Plan
    seats: list[SeatPlan]
    keys: np.ndarray         # (K, 4): layout, free column, y column, x column

    def columns(self, sigma: np.ndarray) -> np.ndarray:
        return self.chip_plan.columns(sigma)

    def all_terminal_values(self, cols: np.ndarray) -> np.ndarray:
        """(seats, 169, terminals) ICM chips: the drop-in for `seqbr.audit(..., U=...)`."""
        C = _c_keys(self.keys, cols)                       # (169, K)
        terminals = len(self.tree.terminals)
        out = np.zeros((len(self.seats), N, terminals))
        for p in self.seats:
            v = _simple_values(p, cols)
            np.add.at(out[p.seat].T, p.s_zid, v.T)
            if len(p.t_zid):
                reach = _reach_from(p.t_others, p.players, cols)
                w = p.t_coef * reach
                np.add.at(out[p.seat].T, p.t_zid, (w * C[:, p.t_key]).T)
        return out


def _seq_ids(tree, z, seat: int) -> tuple[int, ...]:
    return tuple(tree.nodes[i].seq(a) for i, a in z.path if tree.nodes[i].seat == seat)


def plan(tree: floor3.Tree, payouts: icm.Payouts, chip_plan: pricer3.Plan | None = None) -> Plan:
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
            raise KeyError(f"chip_plan never registered the product column {ids}")
        return index_of[ids]

    worth = seqbr._worth(seqbr3.from_floor3(tree), payouts)

    seats: list[SeatPlan] = []
    keys: dict[tuple[int, int, int, int], int] = {}
    for seat in range(n):
        opp = [j for j in range(n) if j != seat]
        simple: list = []
        orders: list = []
        for z in tree.terminals:
            w = worth[z.index]
            col = {j: col_of(_seq_ids(tree, z, j)) for j in opp}

            def others(skip) -> list[int]:
                return [one if j in skip else col[j] for j in opp]

            alive = z.live
            if len(alive) == 1:
                simple.append((z.index, FIXED, w[alive][seat], one, one, others(())))
            elif len(alive) == 2:
                a, b = alive
                if seat in alive:
                    rival = b if seat == a else a
                    lose, win = w[(rival, seat)][seat], w[(seat, rival)][seat]
                    simple.append((z.index, FIXED, lose, one, one, others(())))
                    simple.append((z.index, TWO, win - lose, col[rival], one, others((rival,))))
                else:
                    b_wins, a_wins = w[(b, a)][seat], w[(a, b)][seat]
                    simple.append((z.index, FIXED, b_wins, one, one, others(())))
                    simple.append((z.index, PAIR, a_wins - b_wins, col[a], col[b], others(alive)))
            else:
                free_seat = seat if seat in alive else alive[0]
                free = HERO if seat in alive else col[free_seat]
                for order, row in w.items():
                    if row[seat] == 0.0:      # only saves work: a zero term adds nothing
                        continue
                    y, zz = (s for s in order if s != free_seat)
                    key = (order.index(free_seat), free, col[y], col[zz])
                    if key not in keys:
                        keys[key] = len(keys)
                    orders.append((z.index, row[seat], key, others(alive)))
        simple = simple or [(0, FIXED, 0.0, one, one, [one] * (n - 1))]
        s = list(zip(*simple))
        t = list(zip(*orders)) if orders else [(), (), (), ()]
        seats.append(SeatPlan(
            seat, n,
            np.array(s[0], dtype=np.int64), np.array(s[1], dtype=np.int64),
            np.array(s[2], dtype=float), np.array(s[3], dtype=np.int64),
            np.array(s[4], dtype=np.int64),
            np.array(s[5], dtype=np.int64).reshape(len(simple), n - 1),
            np.array(t[0], dtype=np.int64), np.array(t[1], dtype=float),
            np.array(t[3], dtype=np.int64).reshape(len(orders), n - 1),
            np.array([keys[k] for k in t[2]], dtype=np.int64)))
    key_array = np.zeros((len(keys), 4), dtype=np.int64)
    for k, i in keys.items():
        key_array[i] = k
    return Plan(tree, chip_plan, seats, key_array)


def _reach_from(others: np.ndarray, players: int, cols: np.ndarray) -> np.ndarray:
    """Product of the opponents' line reaches. (169, rows), or (1, rows) if constant.

    Identical to `pricer3._reach_from`; for n >= 3 the independent-deal model makes every reach a
    scalar (hand-independent), so this is a (1, rows) row that broadcasts.
    """
    if players == 2:
        return (hands.M @ cols)[:, others].prod(axis=2)
    scalar = hands.PRIOR @ cols
    return scalar[others].prod(axis=1)[None, :]


def _simple_values(p: SeatPlan, cols: np.ndarray) -> np.ndarray:
    """(169, rows): the terms with no 3-way finish order."""
    special = np.ones((N, len(p.s_kind)))
    two = p.s_kind == TWO
    if two.any():
        special[:, two] = pricer._two_way(p.players == 2) @ cols[:, p.s_rival[two]]
    pair = p.s_kind == PAIR
    if pair.any():
        a = hands.PRIOR[:, None] * cols[:, p.s_rival[pair]]
        special[:, pair] = (a * (_pair() @ cols[:, p.s_second[pair]])).sum(axis=0)
    return p.s_coef * special * _reach_from(p.s_others, p.players, cols)


def _c_keys(keys: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """(169, K): C[layout](y, x)[h] for every distinct key, and the bystander scalar for the
    keys whose free hand is summed over (`free` is then a column, not HERO).

    One tensor contraction per (layout, y, x). Within a layout the outer products of all keys are
    stacked and the contraction is a single (169, 169*169) x (169*169, K_l) matrix product, which
    is the difference between this and one `einsum` per term.
    """
    layout, free, y, x = keys.T
    # `_layouts()` already carries PRIOR on the y and x axes; the free hand's PRIOR is applied
    # below, since it is axis 0 of the tensor and `both` does not reach it.
    yv = cols[:, y].astype(np.float32)
    xv = cols[:, x].astype(np.float32)
    out = np.zeros((N, len(keys)))
    for ell, tensor in enumerate(_layouts()):
        pick = np.flatnonzero(layout == ell)
        for lo in range(0, len(pick), CHUNK):
            sl = pick[lo:lo + CHUNK]
            # (g, key) x (k, key) -> (g, k, key) -> (g*N + k, key): the tensor's own flattening
            flat = np.einsum("gm,km->gkm", yv[:, sl], xv[:, sl]).reshape(N * N, -1)
            out[:, sl] = tensor @ flat
    here = np.flatnonzero(free != HERO)
    if len(here):
        w = (hands.PRIOR[:, None] * cols[:, free[here]]).astype(np.float32)
        out[:, here] = (w * out[:, here]).sum(axis=0)
    return out


class FastAuditor:
    """Drop-in for `seqbr3.Auditor` on the same `seqbr.Game`, ICM payouts.

    Same `seqbr.audit` math -- only the terminal values are batched. Cross-checked against
    `seqbr3.Auditor` in `verify_fasticm3.py` before it is trusted for anything.
    """

    def __init__(self, game: seqbr.Game, plan: Plan, payouts: icm.Payouts):
        self.game = game
        self.plan = plan
        self.payouts = payouts

    def audit(self, sigma: np.ndarray) -> seqbr.Report:
        cols = self.plan.columns(sigma)
        U = self.plan.all_terminal_values(cols)
        return seqbr.audit(self.game, sigma, self.payouts, None, U=U)


def build(game: seqbr.Game, tree: floor3.Tree, payouts: icm.Payouts,
          chip_plan: pricer3.Plan | None = None) -> FastAuditor:
    return FastAuditor(game, plan(tree, payouts, chip_plan), payouts)
