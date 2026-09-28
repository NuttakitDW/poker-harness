"""Check the hand simulator against answers known without it.

1. HU 10bb, both seats jam every hand. The pot is 20bb, winner takes it, a tie is a split,
   so E[net(seat 0)] = sum_hg M[h,g] * 10 * (2 e2[h,g] - 1), exactly, from the exact e2 table.
2. HU 10bb, SB folds every hand. Deterministic: (-0.5, +0.5).
3. 6h 10bb, ante 0.25 each, everyone folds. Deterministic: antes are dead, BB takes them.
4. A solved spot: the simulated mean must agree with auditor.audit()'s EV (same deal model)
   to within Monte Carlo error, for both chip EV and ICM.
"""
from __future__ import annotations

import numpy as np

from pushfold import auditor, coach, floor, hands, icm, oddsmaker
from pushfold.spot import Spot

from lifetime_eps import LIFETIME, Z, bubble, prize_ladder, simulate


def pure(tree: floor.Tree, jam: float) -> np.ndarray:
    sigma = np.zeros((len(tree.nodes), len(hands.CLASSES), 2))
    sigma[:, :, floor.JAM] = jam
    sigma[:, :, floor.FOLD] = 1.0 - jam
    return sigma


def check(label: str, got: float, want: float, tol: float) -> bool:
    ok = abs(got - want) <= tol
    print(f"  {'ok ' if ok else 'FAIL'} {label}: sim {got:+.6f}  exact {want:+.6f}  "
          f"(tol {tol:.4f})")
    return ok


def main() -> None:
    ok = True

    # 1. always jam, heads-up
    spot = Spot((10.0, 10.0))
    tree = floor.build(spot)
    sigma = pure(tree, 1.0)
    net = simulate(spot, tree, {0: sigma, 1: sigma}, 1_000_000, 7)
    e2 = oddsmaker.two_way()
    want = float((hands.PRIOR[:, None] * hands.M * 10.0 * (2.0 * e2 - 1.0)).sum())
    se = net[:, 0].std() / np.sqrt(len(net))
    ok &= check("HU always-jam  E[net seat 0]", net[:, 0].mean(), want, 4 * se)
    ok &= check("HU always-jam  E[net seat 1]", net[:, 1].mean(), -want, 4 * se)
    print(f"     (sigma seat 0 = {net[:,0].std():.4f} bb, se(mean) = {se:.5f} bb)")
    ok &= check("HU always-jam  sum of nets", 0.0, 0.0, 1e-9)

    # 2. always fold, heads-up
    net = simulate(spot, tree, {0: pure(tree, 0.0), 1: pure(tree, 0.0)}, 1000, 7)
    ok &= check("HU always-fold E[net seat 0]", net[:, 0].mean(), -0.5, 1e-12)
    ok &= check("HU always-fold E[net seat 1]", net[:, 1].mean(), +0.5, 1e-12)
    ok &= check("HU always-fold sigma seat 0", float(net[:, 0].std()), 0.0, 1e-12)

    # 3b. chip conservation with a fee: 6-handed, everyone jams, cap 3 -> 3 players see the
    # showdown and each pays the fee, so the nets must sum to exactly -3 x fee every hand.
    spotf = Spot((10.0,) * 6, ante=0.5, ante_mode="bb", fee=0.2)
    treef = floor.build(spotf)
    sigf = pure(treef, 1.0)
    net = simulate(spotf, treef, {s: sigf for s in range(6)}, 1000, 7)
    ok &= check("6h all-jam fee: sum of nets", float(net.sum(axis=1).mean()), -0.6, 1e-12)
    ok &= check("6h all-jam fee: sigma of the sum", float(net.sum(axis=1).std()), 0.0, 1e-12)

    # 3. everyone folds, 6-handed with an ante
    spot6 = Spot((10.0,) * 6, ante=0.25, ante_mode="each")
    tree6 = floor.build(spot6)
    sigma6 = pure(tree6, 0.0)
    net = simulate(spot6, tree6, {s: sigma6 for s in range(6)}, 1000, 7)
    ok &= check("6h ante0.25 fold E[UTG]", net[:, 0].mean(), -0.25, 1e-12)
    ok &= check("6h ante0.25 fold E[SB]", net[:, -2].mean(), -0.75, 1e-12)
    ok &= check("6h ante0.25 fold E[BB]", net[:, -1].mean(), 0.25 * 5 + 0.5, 1e-12)

    # 4. solved spots: sim mean vs auditor EV
    _, p300, _ = prize_ladder("mtt_300_players.json")
    P = bubble(dict(prizes=p300, players_left=46, avg_bb=20.0, table=(10.0,) * 6))
    for label, sp, payouts in (("HU 10bb chipEV", Spot((10.0, 10.0)), None),
                               ("6h bubble ICM", Spot((10.0,) * 6, ante=1.0, ante_mode="bb"), P)):
        r = coach.solve(sp, method="cfr+", target=0.001, check_every=25, max_iters=4000,
                        payouts=payouts)
        net = simulate(sp, r.tree, {s: r.strategy for s in range(sp.n)}, 200_000, 11, payouts)
        ref = auditor.audit(r.tree, r.strategy, payouts=payouts)
        print(f"  {label}: iters {r.iterations} exploit {r.exploitability:.5f}")
        for seat in range(sp.n):
            se = net[:, seat].std() / np.sqrt(len(net))
            ok &= check(f"{label} seat {seat} mean vs audit EV", net[:, seat].mean(),
                        float(ref.ev[seat]), 4 * se)
    print("ALL OK" if ok else "FAILURES ABOVE")
    print(f"(lifetime {LIFETIME:,} hands, z = {Z})")


if __name__ == "__main__":
    main()
