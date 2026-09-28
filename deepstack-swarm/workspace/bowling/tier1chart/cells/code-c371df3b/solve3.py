"""Tier 1 ("open or jam") solver: `floor3.build(..., tier1=True)` + `coach3`/`pricer3` (chip EV,
production speed) or `coach3`/`icm_pricer3` (ICM, production speed) with `seqbr3.Auditor` wired in
as the stop rule, checked every `check_every` iterations (Burch thesis Sec 3.3.1: a check costs
about one iteration, so check infrequently, not every step). This is the piece bowling's
`open3bet-design.md` Sec 6b / next-assignment note asked for; nothing here is a new design, it is
`coach3` + `pricer3`/`icm_pricer3` + `seqbr3` wired together.

Chip EV uses `seqbr3.FastAuditor` (batched, ~130x faster than the generic oracle,
`burch-tier1-solve.md` Sec 4). ICM now uses `fasticm3.FastAuditor` (`burch-fasticm3.md`): the same
batching recipe, so an ICM check costs 0.005s / 0.007s / 0.05s / 0.23s at n=3/4/6/9 instead of
0.21s / 1.26s / 12.0s / 92s, and `check_every` can go back to the Sec 3.3.1 value (a check costs
about one iteration, so check every few, not every step). `fast=False` keeps the old
`seqbr3.Auditor` path as the reference; the two agree to float32 precision (`verify_fasticm3.py`).
"""

from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pushfold import icm  # noqa: E402

import coach3  # noqa: E402
import fasticm3  # noqa: E402
import floor3  # noqa: E402
import icm_pricer3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402


@dataclasses.dataclass
class Solved:
    tree: floor3.Tree
    st: coach3.State
    game: object
    history: list[tuple[int, float]]     # (iteration, exact max gain, chip EV bb/hand)
    seconds: float
    converged: bool


def _require_leaf_free(tree: floor3.Tree) -> None:
    """Refuse a tree whose endings include a FLOP terminal.

    `icm_pricer3`/`pricer3` settle a FLOP terminal with `cashier3.checkdown`, which is the L0
    leaf (`leaf-model-L0.md`), and `icm_pricer3.py:25`'s "no leaf model is consulted here" holds
    only when there is no such terminal. At *unequal* stacks Tier 1 has them
    (`bowling-tier1-flop-gap.md`, `burch-tier1-flop-gap.md`), and nothing downstream said so.
    Call this, or pass `require_leaf_free=True`, before trusting a number from an uneven spot.
    """
    k = tree.counts().get(floor3.FLOP, 0)
    if k:
        raise ValueError(
            f"tree has {k} FLOP terminal(s): those endings are priced by the L0 checkdown leaf, "
            "so this is not a leaf-free Tier 1 solve (it happens whenever the stacks are "
            "unequal). Build with behind_cap=1 for a leaf-free tree, or pass through a real "
            "leaf model. See burch-tier1-flop-gap.md.")


def solve(tree: floor3.Tree, target: float, method: str = "cfr+",
          check_every: int = 25, max_iters: int = 20000,
          require_leaf_free: bool = False) -> Solved:
    if require_leaf_free:
        _require_leaf_free(tree)
    plan = pricer3.plan(tree)
    st = coach3.start(tree, plan)
    game = seqbr3.from_floor3(tree)
    aud = seqbr3.FastAuditor(game, plan)
    return _run(tree, plan, st, game, aud, target, method, check_every, max_iters)


def solve_icm(tree: floor3.Tree, payouts: icm.Payouts, target: float, method: str = "cfr+",
              check_every: int = 25, max_iters: int = 20000, fast: bool = True) -> Solved:
    """Same as `solve`, ICM payouts. `fast=True` uses `fasticm3.FastAuditor` (a check costs ~1
    iteration at every n), `fast=False` the reference `seqbr3.Auditor` (a check costs 537
    iterations at n=9 -- only for cross-checking a number you already have)."""
    plan = icm_pricer3.plan(tree, payouts)
    st = coach3.start(tree, plan)
    game = seqbr3.from_floor3(tree)
    aud = (fasticm3.FastAuditor(game, fasticm3.plan(tree, payouts, plan), payouts)
           if fast else seqbr3.Auditor(game, payouts))
    return _run(tree, plan, st, game, aud, target, method, check_every, max_iters)


def _run(tree, plan, st, game, aud, target, method, check_every, max_iters) -> Solved:
    history: list[tuple[int, float]] = []
    t0 = time.perf_counter()
    converged = False
    for it in range(1, max_iters + 1):
        coach3.iterate(st, method)
        if it % check_every == 0:
            rep = aud.audit(st.average())
            history.append((it, rep.exploitability))
            if rep.exploitability <= target:
                converged = True
                break
    return Solved(tree, st, game, history, time.perf_counter() - t0, converged)


def main() -> None:
    from pushfold.spot import Spot
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    stack = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    target = float(sys.argv[3]) if len(sys.argv) > 3 else 0.001
    method = sys.argv[4] if len(sys.argv) > 4 else "cfr+"
    mode = sys.argv[5] if len(sys.argv) > 5 else "chip"
    spot = Spot(stacks=(stack,) * n)
    tree = floor3.build(spot, tier1=True)
    unit = "bb/hand" if mode == "chip" else "ICM chips/hand"
    print(f"n={n} stack={stack}bb {method} {mode} target={target} {unit}: "
          f"{len(tree.nodes)} nodes, {len(tree.terminals)} terminals {tree.counts()}")
    if mode == "chip":
        sol = solve(tree, target, method)
    else:
        field = (stack,) * max(0, 4 - n)
        payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=field)
        print(f"  ICM 50/30/20, field={field}")
        sol = solve_icm(tree, payouts, target, method)
    print(f"{'converged' if sol.converged else 'DID NOT converge'} in "
          f"{sol.history[-1][0]} iters, {sol.seconds:.2f}s "
          f"({sol.seconds/sol.history[-1][0]*1000:.2f} ms/iter incl. audits)")
    for it, gain in sol.history:
        print(f"  iter {it:>6}  exact max gain {gain:.6f} {unit}")


if __name__ == "__main__":
    main()
