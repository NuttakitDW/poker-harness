"""Cross-evaluation: what a chart from one arm is worth in another arm's game.

Each arm is a different game, so its own exploitability says nothing about the choice between
them. The decision-relevant number is a *profile's expected value inside one fixed game*. Two
directions, both exactly computable with `seqbr.audit`'s `Report.ev`:

  asis -> leafree : take the as-is chart, project it into the leaf-free game (at a decision the
                    leaf-free cap deleted, the seat folds), read the per-seat EV.
  leafree -> asis : the same the other way.

Also cross-checks `reach.terminal_reach` against `seqbr.reach_probability` (johanson's own
implementation) on every arm -- the Cepheus reporting bug was only found by a second codebase.

Usage: .venv/bin/python cross.py <spot> <mode>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/burch/open3bet"))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/johanson"))
sys.path.insert(0, str(HERE))

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import floor3  # noqa: E402
import seqbr  # noqa: E402
import seqbr3  # noqa: E402
import ab as A  # noqa: E402
import reach as R  # noqa: E402

N = len(hands.CLASSES)
ARMS = {"asis": ({}, None), "leafree": ({"behind_cap": 1}, None), "stackoff": ({}, 1.0)}


def build(stacks, arm):
    kw, dial = ARMS[arm]
    tree = floor3.build(Spot(stacks=stacks), tier1=True, **kw)
    return A.stackoff(tree, dial) if dial is not None else tree


def key_of(nd):
    return (nd.seat, tuple(nd.actions), nd.history)


def embed(src_tree, src_sigma, dst_tree) -> np.ndarray:
    """src chart as a strategy on dst: matched nodes copy, unmatched dst nodes play uniform,
    src nodes with no dst counterpart are simply never reached (that seat folds instead)."""
    key = {key_of(nd): nd.index for nd in src_tree.nodes}
    out = np.zeros((len(dst_tree.nodes), N, dst_tree.max_actions))
    for nd in dst_tree.nodes:
        j = key.get(key_of(nd))
        k = len(nd.actions)
        out[nd.index, :, :k] = (src_sigma[j, :, :k] if j is not None
                                else np.ones((N, k)) / k)
    return out


def main() -> None:
    spot, mode = sys.argv[1], sys.argv[2]
    stacks = A.SPOTS[spot]
    napz = np.load(HERE / f"ab-{spot}-{mode}.npz")
    pay = A.payouts_for(stacks, A.LEFT) if mode == "icm" else None
    unit = "ICM chips/hand" if pay else "bb/hand"
    trees = {a: build(stacks, a) for a in ARMS}
    sig = {a: napz[f"{a}_sigma"] for a in ARMS if f"{a}_sigma" in napz}
    games = {a: seqbr3.from_floor3(t) for a, t in trees.items()}
    print(f"=== {spot} {stacks} {mode}  ({unit})")
    # reach cross-check first
    for a, t in trees.items():
        mine = R.terminal_reach(t, sig[a])
        theirs = seqbr.reach_probability(games[a], sig[a])
        print(f"  reach cross-check {a:>9}: sum(mine)={mine.sum():.6f} "
              f"sum(seqbr)={theirs.sum():.6f} max|diff|={np.abs(mine-theirs).max():.2e}")
    # cross evaluation
    ev = {}
    for arm in sig:
        ev[arm] = {}
        for game_arm, g in games.items():
            s = embed(trees[arm], sig[arm], trees[game_arm])
            ev[arm][game_arm] = seqbr.audit(g, s, pay).ev
    print("  per-seat EV (seat order as in spot), profiles from rows evaluated in columns:")
    for src in sig:
        row = "   ".join(f"{name}: " + np.array2string(ev[src][name], precision=4)
                         for name in games)
        print(f"    {src:>9}  {row}")
    for src in sig:
        for dst in games:
            if src != dst:
                loss = ev[src][src] - ev[src][dst]
                print(f"    cost of playing {src:>9} in {dst:>9}: "
                      f"max seat {loss.max():+.5f} {unit}  (per seat "
                      f"{np.array2string(loss, precision=5)})")


if __name__ == "__main__":
    main()
