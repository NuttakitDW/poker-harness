"""Two independent checks on the sequential best response.

1. Brute force. `U[seat]` does not depend on the seat's own strategy, so a seat's best response
   per hand class is the max over its *pure plans* (one action at each of its nodes) of the sum
   of `u_z` over the endings that plan can reach. Enumerate all plans and compare with the
   backward-induction walk. This is the small-game audit of the auditor that IJCAI 2011's
   accelerated best response was itself checked against.

2. Ranking. Does the old shortcut order two strategies the same way the exact best response
   does? If it does not, then "cfr+ beat dcfr" and "L0 beat L1" conclusions drawn from it are
   not safe, which is the IJCAI 2011 point about head-to-head results transferred to a
   mis-specified exploitability measure.

Run: .venv/bin/python deepstack-swarm/workspace/johanson/brute_force_check.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seqbr  # noqa: E402
import toy_open3bet as toy  # noqa: E402
from pushfold import hands, icm  # noqa: E402

N = len(hands.CLASSES)
PRIOR = hands.PRIOR
PAYOUTS = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(12.0, 12.0))


def reachable(game: seqbr.Game, seat: int, plan: dict[int, int]) -> list[int]:
    """Endings a pure plan for `seat` can reach; every other seat is free to do anything."""
    out = []

    def go(index: int) -> None:
        if index < 0:
            out.append(~index)
            return
        node = game.nodes[index]
        actions = ([plan[node.index]] if node.seat == seat
                   else range(len(node.children)))
        for a in actions:
            go(node.children[a])

    go(game.root)
    return out


def brute_force(game: seqbr.Game, U: np.ndarray, seat: int) -> np.ndarray:
    """Best-response value per hand class, by enumerating pure plans."""
    my_nodes = game.nodes_of(seat)
    best = np.full(N, -np.inf)
    for choice in itertools.product(*[range(len(n.children)) for n in my_nodes]):
        plan = dict(zip([n.index for n in my_nodes], choice))
        value = U[seat][:, reachable(game, seat, plan)].sum(axis=1)
        best = np.maximum(best, value)
    return best


def main() -> None:
    rng = np.random.default_rng(11)
    game = toy.build(12.0)
    print(f"toy open/3bet heads-up 12bb, L0 flop leaf. "
          f"pure plans per seat: "
          f"{[np.prod([len(n.children) for n in game.nodes_of(s)]) for s in range(2)]}")
    worst = 0.0
    for mode, payouts in (("chipEV", None), ("ICM", PAYOUTS)):
        for trial in range(20):
            sigma = (game.uniform() if trial == 0
                     else __import__("shortcut_sweep").random_sigma(game, rng, (0.05, 0.5, 5.0)[trial % 3]))
            U = seqbr.values(game, sigma, payouts)
            report = seqbr.audit(game, sigma, payouts, U=U)
            for seat in range(game.spot.n):
                walk = seqbr._walk(game, U[seat], sigma, seat, best=True)
                force = brute_force(game, U, seat)
                worst = max(worst, float(np.abs(walk - force).max()))
        print(f"{mode}: worst |walk - brute force| per hand class over 20 strategies: {worst:.3e}")
    assert worst < 1e-12, "backward induction and brute force disagree"
    print("PASS: the backward-induction best response equals the enumerated pure best response.\n")

    for mode, payouts in (("chipEV", None), ("ICM", PAYOUTS)):
        reports = []
        for trial in range(120):
            sigma = __import__("shortcut_sweep").random_sigma(game, rng, (0.05, 0.5, 5.0)[trial % 3])
            reports.append(seqbr.audit(game, sigma, payouts))
        exact = np.array([r.exploitability for r in reports])
        short = np.array([r.shortcut.max() for r in reports])
        pairs = [(i, j) for i in range(len(exact)) for j in range(i + 1, len(exact))]
        bad = sum(1 for i, j in pairs
                  if np.sign(exact[i] - exact[j]) != np.sign(short[i] - short[j]))
        print(f"{mode}: of {len(pairs)} strategy pairs, the shortcut ranks {bad} "
              f"({bad / len(pairs):.1%}) in the wrong order "
              f"(correlation {np.corrcoef(exact, short)[0, 1]:.4f})")


if __name__ == "__main__":
    main()
