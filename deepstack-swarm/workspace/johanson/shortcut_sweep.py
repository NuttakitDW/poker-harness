"""Can the push/fold shortcut ever UNDER-report exploitability on a sequential tree?

Theory says no: the sum of immediate counterfactual regrets bounds the full counterfactual
regret, i.e. the best-response gain (Zinkevich, Johanson, Bowling, Piccione, *Regret
Minimization in Games with Incomplete Information*, NIPS 2007). A bound with the wrong
direction would make the stop rule in `pushfold/coach.py` unsafe rather than merely wasteful,
so it is worth 2000 random strategies and a stack sweep.

Run: .venv/bin/python deepstack-swarm/workspace/johanson/shortcut_sweep.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seqbr  # noqa: E402
import toy_open3bet as toy  # noqa: E402
from pushfold import hands, icm  # noqa: E402

N = len(hands.CLASSES)
PAYOUTS = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(12.0, 12.0))


def random_sigma(game, rng, sharpness):
    """Dirichlet-ish: sharpness -> 0 gives near-pure strategies, large gives near-uniform."""
    shape = (len(game.nodes), N, game.width)
    s = np.zeros(shape)
    for node in game.nodes:
        k = len(node.children)
        r = rng.gamma(sharpness, size=(N, k)) + 1e-300
        s[node.index, :, :k] = r / r.sum(axis=1, keepdims=True)
    return s


def main() -> None:
    rng = np.random.default_rng(7)
    game = toy.build(12.0)
    print("2000 random strategies, toy open/3bet heads-up 12bb, L0 flop leaf.")
    print("ratio = shortcut / exact, per seat, over every seat and strategy.\n")
    for mode, payouts in (("chipEV", None), ("ICM", PAYOUTS)):
        ratios, worst = [], None
        for i in range(1000):
            sharp = (0.05, 0.5, 5.0)[i % 3]
            sigma = random_sigma(game, rng, sharp)
            r = seqbr.audit(game, sigma, payouts)
            for seat in range(game.spot.n):
                if r.gain[seat] > 1e-9:
                    ratio = r.shortcut[seat] / r.gain[seat]
                    ratios.append(ratio)
                    if worst is None or ratio < worst[0]:
                        worst = (ratio, i, seat, sharp, r.gain[seat], r.shortcut[seat])
                elif r.shortcut[seat] < -1e-12:
                    print("  NEGATIVE shortcut with zero gain:", i, seat)
        ratios = np.array(ratios)
        print(f"{mode}: n={len(ratios)}  min ratio {ratios.min():.6f}  median {np.median(ratios):.3f}  "
              f"max {ratios.max():.3f}")
        print(f"   least conservative case: ratio {worst[0]:.6f} (seat {worst[2]}, sharpness {worst[3]}, "
              f"exact {worst[4]:.6f}, shortcut {worst[5]:.6f})")
        print(f"   share of cases where the shortcut over-reports by >1.5x: "
              f"{float((ratios > 1.5).mean()):.1%}")

    print("\nStack sweep at a CFR+ near-equilibrium (400 iterations each).")
    print(f"{'stack':>6} {'mode':<7} {'exact max':>11} {'NashConv':>10} {'shortcut':>10} {'ratio':>7} {'%pot':>7}")
    for stack in (8.0, 12.0, 20.0, 30.0):
        g = toy.build(stack)
        for mode, payouts in (("chipEV", None), ("ICM", PAYOUTS)):
            average, history = toy.solve(g, 400, payouts, check=400, log=None)
            r = history[-1][1]
            print(f"{stack:6.0f} {mode:<7} {r.exploitability:11.6f} {r.nashconv:10.6f} "
                  f"{r.shortcut.max():10.6f} {r.shortcut.max() / max(r.exploitability, 1e-12):6.2f}x "
                  f"{seqbr.as_pct_of_pot(r.exploitability, g.spot):6.2f}")


if __name__ == "__main__":
    main()
