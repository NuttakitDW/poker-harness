"""johanson's sequential best response (`workspace/johanson/seqbr.py`), wired onto `floor3.Tree`.

Nothing about the audit math is rewritten here -- `seqbr.Game`/`audit`/`chip_values`/`icm_values`
already work on a generic ragged-action tree (johanson wrote them that way on purpose so this
adapter would be small). What is new:

1. `from_floor3`: the same kind of history-lookup adapter as `seqbr.from_floor` (built for
   `pushfold.floor`), generalised to floor3's ragged actions and its "forced folds get no node"
   convention (`floor3.build`'s cap rule: a seat with only FOLD legal gets no node and no path
   entry, so a child history can skip straight past it to the next real decision or terminal --
   this holds for both node histories and terminal paths, so the same lookup resolves both).
   `coach3`'s sigma array can be passed to `seqbr.audit` unmodified: node indices line up 1:1
   (built in the same order) and `seqbr`'s functions only ever read `sigma[node.index, :, :k]`
   for `k` = that node's own number of actions, so the padding in `coach3`'s wider
   `(nodes, 169, max_actions)` array is never touched.

2. `worth_cache` / `audit`: `bowling`'s `bowling-tier1-first-solve.md` measured the reference
   engine recomputing `seqbr._worth` -- a full permutation-times-`icm.value` pass over every
   ending -- from scratch on every call, because the tree and payouts never change between CFR
   iterations or between exploitability checks. This module computes it once per (game, payouts)
   and reuses it, which is the fix bowling's finding asked for, applied here rather than in
   `seqbr.py` itself (not our file to edit).

Tier 1 only: every ending is ALLFOLD/UNCONTESTED/SHOWDOWN, so `cashier3.price_terminal`'s mixture
always has exactly one component and `from_floor3` asserts that. A leaf with >1 component (Tier 2)
needs `seqbr.Ending`/`chip_values`/`icm_values` extended to a mixture first -- moravcik's and
johanson's problem, not solved here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from pushfold import icm

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "johanson"))
import seqbr  # noqa: E402  (johanson's module)

import cashier3
import floor3
import pricer3

N = seqbr.N
PRIOR = seqbr.PRIOR


def from_floor3(tree: floor3.Tree, leaf: cashier3.Leaf = cashier3.checkdown) -> seqbr.Game:
    by_history = {n.history: n for n in tree.nodes}
    ending_of: dict[tuple, int] = {}
    endings: list[seqbr.Ending] = []
    for z in tree.terminals:
        hist = tuple((tree.nodes[i].seat, a) for i, a in z.path)
        mix = cashier3.price_terminal(tree.spot, z, leaf)
        if len(mix) != 1:
            raise NotImplementedError("seqbr3 does not support mixture leaves yet (Tier 2)")
        _, settle = mix[0]
        pot = float(sum(z.invested) + sum(tree.spot.antes))
        endings.append(seqbr.Ending(len(endings), z.live, settle, z.kind, pot))
        ending_of[hist] = endings[-1].index

    def resolve(hist: tuple) -> int:
        if hist in by_history:
            return by_history[hist].index
        return ~ending_of[hist]

    nodes = tuple(
        seqbr.Node(nd.index, nd.seat,
                   tuple(resolve(nd.history + ((nd.seat, a),)) for a in nd.actions), nd.labels)
        for nd in tree.nodes)
    root = nodes[0].index if nodes else ~ending_of[()]
    return seqbr.Game(tree.spot, nodes, tuple(endings), root)


class FastAuditor:
    """Chip EV only. Same `seqbr.audit` math, but the terminal values come from
    `pricer3.all_terminal_values` (batched across all terminals, `tier1-audit-speed.md`) instead
    of `seqbr.chip_values`'s per-terminal Python loop -- ~130x faster at n=9 (8.0s -> 0.06s,
    measured, max |diff| 1e-8), because backward induction itself (`seqbr._walk`) was never the
    bottleneck: 37ms for 2 x 9 seats on the same tree. This is `coach3`'s `pricer3.Plan`, so no
    ICM: `pricer3` has no ICM pricer for OPEN3BET. Use `Auditor` for that (slow, reference-only).
    """

    def __init__(self, game: seqbr.Game, plan: pricer3.Plan):
        self.game = game
        self.plan = plan

    def audit(self, sigma: np.ndarray) -> seqbr.Report:
        U = pricer3.all_terminal_values(self.plan, sigma)
        return seqbr.audit(self.game, sigma, None, U=U)


class Auditor:
    """`seqbr.audit`, with `_worth` (the ICM permutation table) built once and reused.

    Cross-checked against uncached `seqbr.audit` in `verify_seqbr3.py` before this class is
    trusted for anything -- see that file for the numbers.
    """

    def __init__(self, game: seqbr.Game, payouts: icm.Payouts | None = None,
                 leaf: seqbr.Leaf | None = None):
        self.game = game
        self.payouts = payouts
        self.leaf = leaf or seqbr.tables()
        self.worth = seqbr._worth(game, payouts) if payouts is not None else None

    def values(self, sigma: np.ndarray) -> np.ndarray:
        paths = seqbr.path_columns(self.game, sigma)
        if self.payouts is None:
            return seqbr.chip_values(self.game, paths, self.leaf)
        return _icm_values_cached(self.game, paths, self.payouts, self.worth, self.leaf)

    def audit(self, sigma: np.ndarray) -> seqbr.Report:
        return seqbr.audit(self.game, sigma, self.payouts, self.leaf, U=self.values(sigma))


def _icm_values_cached(game: seqbr.Game, paths: np.ndarray, payouts: icm.Payouts,
                        worth: list[dict], leaf: seqbr.Leaf) -> np.ndarray:
    """Body identical to `seqbr.icm_values`, minus the `_worth(game, payouts)` recomputation."""
    n = game.spot.n
    payouts.check(n)
    O = seqbr._opponent_model(n)
    U = np.zeros((n, N, len(game.endings)))
    for z in game.endings:
        c = paths[z.index]
        R = O @ c.T
        for seat in range(n):
            others = [j for j in range(n) if j != seat]

            def rest(skip) -> np.ndarray:
                keep = [j for j in others if j not in skip]
                return R[:, keep].prod(axis=1) if keep else np.ones(N)

            w = worth[z.index]
            if len(z.alive) == 1:
                u = w[z.alive][seat] * rest(())
            elif len(z.alive) == 2:
                a, b = z.alive
                if seat in z.alive:
                    rival = b if seat == a else a
                    lose, win = w[(rival, seat)][seat], w[(seat, rival)][seat]
                    beat = (O * leaf.e2) @ c[rival]
                    u = lose * rest(()) + (win - lose) * beat * rest([rival])
                else:
                    b_wins, a_wins = w[(b, a)][seat], w[(a, b)][seat]
                    beats = float((PRIOR * c[a]) @ (leaf.e2 * PRIOR[None, :]) @ c[b])
                    u = b_wins * rest(()) + (a_wins - b_wins) * beats * rest(z.alive)
            else:
                free = seat if seat in z.alive else z.alive[0]
                u = np.zeros(N)
                for order, row in w.items():
                    if row[seat] == 0.0:
                        continue
                    y, x = (s for s in order if s != free)
                    axes = seqbr._AXES[order.index(free)]
                    tensor = leaf.orders.transpose(axes)
                    term = np.einsum("hgk,g,k->h", tensor, PRIOR * c[y], PRIOR * c[x])
                    if seat in z.alive:
                        u = u + row[seat] * term * rest(z.alive)
                    else:
                        u = u + row[seat] * float((PRIOR * c[free]) @ term) * rest(z.alive)
            U[seat, :, z.index] = u
    return U
