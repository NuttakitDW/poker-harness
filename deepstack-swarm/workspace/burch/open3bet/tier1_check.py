"""Cross-check for Tier 1 ("open or jam"): floor3-built tree, two independent CFR value oracles,
seqbr3's audit as the stop rule, against bowling's `workspace/bowling/tier1.py` reference numbers.

Two things this answers.

1. Chip EV: does `pricer3`'s flattened-column pricer (fast, production) and `seqbr3`'s generic
   backward-induction oracle (slow, from johanson's `seqbr.py`, reused via `from_floor3`) agree,
   when both are run with the same own-reach-weighted CFR+ average, on the SAME floor3 tree? And
   does that match bowling's independently-built tree/solver?

2. ICM: `pricer3`/`coach3` have no ICM pricer yet (`burch-open3bet-tree-and-cost.md` says so).
   bowling's reference `solve()` (`johanson/toy_open3bet.py`) also has a bug: it accumulates the
   average as `total[index] += t * sigma[index]`, the RAW behaviour probability, with no own-reach
   weight -- exactly the mistake `burch-open3bet-tree-and-cost.md` Sec 5(a) warned about, and Tier 1
   has seats with own reach < 1 (a seat's second decision, facing its own 3bet-less all-in). This
   script's `solve_generic` fixes that, reusing `seqbr3`'s cached-ICM oracle so it doesn't also
   recompute `_worth` every iteration (`bowling-tier1-first-solve.md`'s other flagged bug). It is
   a reference solver for THIS cross-check, not a production ICM path -- OPEN3BET has no ICM
   pricer (a) at all.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "johanson"))

import seqbr  # noqa: E402
from pushfold import icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import coach3  # noqa: E402
import floor3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402

N = seqbr.N


def node_reach(game: seqbr.Game, sigma: np.ndarray, seat: int) -> dict[int, np.ndarray]:
    """pi_seat^sigma(node) at every one of `seat`'s own nodes: the own-reach fix bowling's
    reference solver skips. Full-tree walk -- fine at Tier 1's size, not meant for burch's v0
    tree (that is `coach3.own_reach`, which uses `floor3.Node.own_prev` instead of a walk)."""
    out: dict[int, np.ndarray] = {}

    def walk(index: int, r: np.ndarray) -> None:
        if index < 0:
            return
        node = game.nodes[index]
        if node.seat == seat:
            out[node.index] = r
        for a, child in enumerate(node.children):
            walk(child, r * sigma[node.index, :, a] if node.seat == seat else r)

    walk(game.root, np.ones(N))
    return out


def counterfactual(game: seqbr.Game, u: np.ndarray, sigma: np.ndarray, seat: int) -> dict:
    """Same quantity as `johanson/toy_open3bet.counterfactual`, reused (not reimplemented
    differently) so any disagreement is about the value oracle, not this bookkeeping."""
    out: dict[int, np.ndarray] = {}

    def go(index: int) -> np.ndarray:
        if index < 0:
            return u[:, ~index]
        node = game.nodes[index]
        kids = np.stack([go(child) for child in node.children], axis=1)
        if node.seat != seat:
            return kids.sum(axis=1)
        out[node.index] = kids
        return (sigma[node.index, :, :kids.shape[1]] * kids).sum(axis=1)

    go(game.root)
    return out


def solve_generic(game: seqbr.Game, iters: int, payouts: icm.Payouts | None,
                   check: int, log=print) -> tuple[np.ndarray, list]:
    """CFR+ with own-reach-weighted averaging, over `seqbr.Game`, using seqbr3's cached-worth
    ICM oracle. Cross-check reference only -- Python recursion per seat per iteration, not fast."""
    width = game.width
    shape = (len(game.nodes), N, width)
    regret, total = np.zeros(shape), np.zeros(shape)
    sigma = game.uniform()
    legal = {n.index: len(n.children) for n in game.nodes}
    worth = seqbr._worth(game, payouts) if payouts is not None else None
    history = []
    for t in range(1, iters + 1):
        paths = seqbr.path_columns(game, sigma)
        U = (seqbr.chip_values(game, paths) if payouts is None
             else seqbr3._icm_values_cached(game, paths, payouts, worth, seqbr.tables()))
        for seat in range(game.spot.n):
            cfv = counterfactual(game, U[seat], sigma, seat)
            reach = node_reach(game, sigma, seat)
            for index, kids in cfv.items():
                k = kids.shape[1]
                now = (sigma[index, :, :k] * kids).sum(axis=1, keepdims=True)
                regret[index, :, :k] = np.maximum(regret[index, :, :k] + kids - now, 0.0)
                total[index] += t * reach[index][:, None] * sigma[index]
                pos = np.maximum(regret[index, :, :k], 0.0)
                s = pos.sum(axis=1, keepdims=True)
                sigma[index, :, :k] = np.where(s > 0, pos / np.where(s > 0, s, 1), 1.0 / k)
        if t % check == 0 or t == iters:
            avg = _normalise(total, legal)
            report = seqbr.audit(game, avg, payouts)
            history.append((t, report))
            if log:
                log(f"  iter {t:>5}  exact max gain {report.exploitability: .6f}  "
                    f"shortcut {report.shortcut.max(): .6f}")
    return _normalise(total, legal), history


def _normalise(total: np.ndarray, legal: dict) -> np.ndarray:
    out = np.zeros_like(total)
    for index, k in legal.items():
        s = total[index, :, :k].sum(axis=1, keepdims=True)
        out[index, :, :k] = np.where(s > 0, total[index, :, :k] / np.where(s > 0, s, 1), 1.0 / k)
    return out


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    stack = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    iters = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    spot = Spot(stacks=(stack,) * n)
    tree = floor3.build(spot, tier1=True)
    game = seqbr3.from_floor3(tree)
    print(f"n={n} stack={stack} tree: {len(tree.nodes)} nodes {len(tree.terminals)} terminals "
          f"{tree.counts()}")

    # --- Chip EV: pricer3+coach3 (production) vs seqbr3 generic oracle (reference), same tree ---
    plan = pricer3.plan(tree)
    st = coach3.start(tree, plan)
    t0 = time.time()
    for _ in range(iters):
        coach3.iterate(st, "cfr+")
    avg_fast = st.average()
    aud = seqbr3.Auditor(game, payouts=None)
    rep_fast = aud.audit(avg_fast)
    print(f"\nchip EV via coach3/pricer3 ({time.time()-t0:.2f}s, own-reach avg): "
          f"exact max gain {rep_fast.exploitability:.6f}  shortcut {rep_fast.shortcut.max():.6f}")

    t0 = time.time()
    avg_ref, hist = solve_generic(game, iters, None, check=max(iters // 4, 1), log=None)
    rep_ref = seqbr.audit(game, avg_ref, None)
    print(f"chip EV via seqbr3 generic oracle ({time.time()-t0:.2f}s, own-reach avg): "
          f"exact max gain {rep_ref.exploitability:.6f}  shortcut {rep_ref.shortcut.max():.6f}")
    print("bowling's reference (naive average, no own-reach weight): 0.00089 (400 iters, 15bb, n=3)")

    # --- ICM: no pricer3 support; seqbr3 generic oracle is the only oracle, with the reach fix ---
    field = (stack,) * max(0, 4 - n)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=field)
    t0 = time.time()
    avg_icm, hist_icm = solve_generic(game, iters, payouts, check=max(iters // 4, 1), log=None)
    aud2 = seqbr3.Auditor(game, payouts=payouts)
    rep_icm = aud2.audit(avg_icm)
    print(f"\nICM via seqbr3 generic oracle, own-reach avg ({time.time()-t0:.2f}s, "
          f"field={field}): exact max gain {rep_icm.exploitability:.6f}  "
          f"shortcut {rep_icm.shortcut.max():.6f}")
    print("bowling's reference (naive average, no own-reach weight): 0.00804 (400 iters, 15bb, n=3)")


if __name__ == "__main__":
    main()
