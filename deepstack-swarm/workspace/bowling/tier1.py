"""ICM-OPEN3BET-v0 Tier 1: "open or jam", no flat call, exactly the three ending types
pushfold/ already prices (allfold, uncontested-open, all-in showdown). No leaf model needed.

Actions (equal stacks only in this script; forced/short-stack posting not handled):
  unopened, not BB: fold, open 2.2bb, all-in
  unopened BB:       walk (no node)
  facing an open:    fold, all-in
  facing an all-in:  fold, call
Cap: MAX_ALLIN = 3 (pushfold/floor.py's convention) -- once 3 seats are committed all-in,
remaining seats are forced to fold with no decision node.

This reuses `johanson`'s `seqbr.py` (Game/Node/Ending, values, audit -- the validated
sequential best response) and the settlement helper and generic CFR+ solver from
`johanson/toy_open3bet.py`. Nothing new is claimed about correctness of those two pieces;
they are johanson's, cross-checked in his finding. What is new here is only the tree
builder `build()` and running it to an actual number.

Run: .venv/bin/python deepstack-swarm/workspace/bowling/tier1.py [n] [stack]
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/johanson"))

import seqbr  # noqa: E402
from pushfold import icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

spec = importlib.util.spec_from_file_location("toy", ROOT / "deepstack-swarm/workspace/johanson/toy_open3bet.py")
toy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toy)
settle_bets, solve = toy.settle_bets, toy.solve

MAX_ALLIN = 3


def build(spot: Spot, open_to: float = 2.2) -> seqbr.Game:
    n = spot.n
    S = spot.stacks[0]
    if len(set(spot.stacks)) != 1:
        raise NotImplementedError("this script assumes equal stacks (see docstring)")
    if spot.antes != (0.0,) * n:
        raise NotImplementedError("no ante support in this script")
    nodes: list[seqbr.Node] = []
    endings: list[seqbr.Ending] = []

    def new_node(seat: int, children: tuple, labels: tuple) -> int:
        nodes.append(seqbr.Node(len(nodes), seat, children, labels))
        return nodes[-1].index

    def end(paid: list, alive: tuple, label: str) -> int:
        pot = float(sum(paid))
        endings.append(seqbr.Ending(len(endings), alive, settle_bets(spot, tuple(paid), alive),
                                    label, pot))
        return ~endings[-1].index

    def resolve_allin(queue: list, paid: list, alive: list) -> int:
        if not queue:
            return end(paid, tuple(alive), "showdown " + "".join(str(s) for s in alive))
        seat, rest = queue[0], queue[1:]
        if len(alive) >= MAX_ALLIN:
            return resolve_allin(rest, paid, alive)   # forced fold, no node (floor.py's cap rule)
        fold_child = resolve_allin(rest, paid, alive)
        call_paid = paid.copy()
        call_paid[seat] = S
        call_child = resolve_allin(rest, call_paid, alive + [seat])
        return new_node(seat, (fold_child, call_child), ("fold", "call"))

    def facing_open(seat: int, opener: int, paid: list) -> int:
        if seat == n:
            return end(paid, (opener,), f"open{opener}-uncontested")
        fold_child = facing_open(seat + 1, opener, paid)
        shove_paid = paid.copy()
        shove_paid[seat] = S
        queue = list(range(seat + 1, n)) + [opener]
        shove_child = resolve_allin(queue, shove_paid, [seat])
        return new_node(seat, (fold_child, shove_child), ("fold", "all-in"))

    def first(seat: int, paid: list) -> int:
        if seat == n - 1:
            return end(paid, (n - 1,), "walk")
        fold_child = first(seat + 1, paid)
        open_paid = paid.copy()
        open_paid[seat] = open_to
        open_child = facing_open(seat + 1, seat, open_paid)
        allin_paid = paid.copy()
        allin_paid[seat] = S
        allin_child = resolve_allin(list(range(seat + 1, n)), allin_paid, [seat])
        return new_node(seat, (fold_child, open_child, allin_child),
                        ("fold", f"open {open_to}", "all-in"))

    root = first(0, list(spot.blinds))
    return seqbr.Game(spot, tuple(sorted(nodes, key=lambda x: x.index)), tuple(endings), root)


def count(game: seqbr.Game) -> dict:
    kinds: dict[str, int] = {}
    for e in game.endings:
        k = ("allfold" if e.label == "f" or e.label == "walk" else
             "uncontested" if "uncontested" in e.label else "showdown")
        kinds[k] = kinds.get(k, 0) + 1
    return {"nodes": len(game.nodes), "terminals": len(game.endings), **kinds}


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    stack = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    iters = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    spot = Spot(stacks=(stack,) * n)
    game = build(spot)
    print(f"Tier 1, n={n}, stacks={stack}bb each, open to 2.2bb: {count(game)}")

    field = (stack,) * max(0, 4 - n)   # pad so there is always a real field beyond the table
    for label, payouts in [("chipEV", None),
                            (f"ICM 50/30/20, field={field}",
                             icm.Payouts(prizes=(50.0, 30.0, 20.0), field=field))]:
        unit = "ICM chips/hand" if payouts else "bb/hand"
        t0 = time.time()
        average, history = solve(game, iters, payouts, check=max(iters // 6, 1), log=None)
        dt = time.time() - t0
        t, last = history[-1]
        print(f"\n=== {label} ({unit}) === {dt:.1f}s for {iters} iters, {dt/iters*1000:.2f} ms/it")
        print(f"  after {t} iters: exact gain per seat {np.array2string(last.gain, precision=5)}")
        print(f"  max (=exploitability) {last.exploitability:.5f} {unit}  "
              f"= {seqbr.as_pct_of_pot(last.exploitability, spot):.3f}% of the {seqbr.initial_pot(spot)}bb "
              f"starting pot")
        print(f"  shortcut (pushfold/auditor-style) would report {last.shortcut.max():.5f} "
              f"({last.shortcut.max()/max(last.exploitability,1e-12):.2f}x the truth)")
        pos = spot.names
        jam0 = average[0, :, 2]  # seat 0's first-in "all-in" freq, all classes -- just a sanity print
        print(f"  seat 0 ({pos[0]}) first-in: fold {average[0,:,0].mean()*100:.1f}%  "
              f"open {average[0,:,1].mean()*100:.1f}%  all-in {average[0,:,2].mean()*100:.1f}%  "
              f"(unweighted mean over 169 classes, sanity only)")


if __name__ == "__main__":
    main()
