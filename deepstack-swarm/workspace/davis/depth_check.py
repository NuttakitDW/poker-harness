"""Does the lifetime epsilon move with stack depth? (The stated limit of davis-lifetime-eps.md.)

The main finding measures one depth, 10bb, and says so. sigma is a property of the strategy, so
a different depth is a different strategy and could have a different sigma. This re-runs the same
protocol at 20bb for the two spots that bracket the range (heads-up, and 6-max with a 1bb ante
in bb mode), same solver settings, same 200,000 hands, same seed, and reports sigma and the
lifetime epsilon side by side with the 10bb numbers.
"""
from __future__ import annotations

import numpy as np

from pushfold import coach
from pushfold.spot import Spot

from lifetime_eps import LIFETIME, Z, describe, prize_ladder, bubble, simulate

NHANDS = 200_000
SEED = 20260927
TARGET = 0.001


def run(name, spot, payouts=None):
    r = coach.solve(spot, method="cfr+", target=TARGET, check_every=25, max_iters=20_000,
                    payouts=payouts)
    net = simulate(spot, r.tree, {s: r.strategy for s in range(spot.n)}, NHANDS, SEED, payouts)
    per = describe(net)
    smax = max(p["sigma"] for p in per)
    ses = max(p["se_sigma"] for p in per)
    unit = "ICM chips" if payouts is not None else "bb"
    print(f"{name:<26} n={spot.n} iters={r.iterations:>4} exploit={r.exploitability:.5f} "
          f"sigma_max={smax:.4f} (se {ses:.4f}) eps={Z * smax / np.sqrt(LIFETIME):.6f} "
          f"({1000 * Z * smax / np.sqrt(LIFETIME):.3f} m{unit}/hand)")
    return smax


def main() -> None:
    _, p300, _ = prize_ladder("mtt_300_players.json")
    P = bubble(dict(prizes=p300, players_left=46, avg_bb=20.0, table=(10.0,) * 6))
    print(f"protocol: CFR+ target {TARGET}, {NHANDS:,} hands, seed {SEED}, fee 0")
    for depth in (10.0, 20.0, 30.0):
        run(f"HU-{depth:.0f}bb", Spot((depth, depth)))
    for depth in (10.0, 20.0):
        run(f"6h-{depth:.0f}bb-ante1.0-bb", Spot((depth,) * 6, ante=1.0, ante_mode="bb"))
    for depth in (10.0, 20.0):
        run(f"6h-{depth:.0f}bb-ante1.0-bubble46", Spot((depth,) * 6, ante=1.0, ante_mode="bb"),
            payouts=bubble(dict(prizes=p300, players_left=46, avg_bb=20.0,
                                table=(depth,) * 6)))
    del P


if __name__ == "__main__":
    main()
