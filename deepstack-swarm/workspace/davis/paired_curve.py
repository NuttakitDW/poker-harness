"""sigma_Delta along a chart-interpolation axis, and how it relates to sigma_hand.

bowling's split: sigma_hand (one hand under one chart) is the headline; sigma_Delta (the per-hand
difference between two charts, which is what CRN measures) is the second number. Question: is
sigma_Delta ever below its own lifetime bar while sigma_hand is not?

Setup: bubble spot (6h 10bb, bb-ante 1.0, 46 left of 300). Right chart = solved at bb-ante 1.0;
wrong chart = solved at no ante. sigma(a) = (1-a)*right + a*wrong, evaluated with a = mix level,
all with common random numbers (same deals, same action draws). Chart distance is combo-weighted
dTV vs the right chart. Per-seat "loss" is net(right) - net(mix), positive = the mix loses.

If sigma_Delta(a) ~ a * sigma_Delta(1), then both the mean loss and its bar shrink together and
|loss|/eps_Delta is scale-free -- which is the only sensible way to say whether a lifetime
separates two charts that differ by an arbitrary amount.
"""
from __future__ import annotations

import numpy as np

from pushfold import coach, hands
from pushfold.spot import Spot

from lifetime_eps import LIFETIME, Z, bubble, prize_ladder, simulate, uniforms

MIXES = (0.1, 0.5, 1.0)
NSEAT = 6
NHANDS = 300_000
SEED = 20260927


def mix(a, right, wrong, n):
    """Blend two charts node-by-node, matching on (seat, history).

    Result.strategy is indexed by node, not by seat (shape (n_nodes, 169, 2)); nodes_at in
    simulate uses those global indices. The two spots differ only in payoffs, but to be safe
    the blend is keyed on (seat, history) so a node missing from the wrong chart falls back
    to the right chart rather than to a different node.
    """
    idx = {(nd.seat, nd.history): nd.index for nd in wrong.tree.nodes}
    out = right.strategy.copy()
    for nd in right.tree.nodes:
        j = idx.get((nd.seat, nd.history))
        if j is not None:
            out[nd.index] = (1.0 - a) * right.strategy[nd.index] + a * wrong.strategy[j]
    return {s: out for s in range(n)}


def main() -> None:
    _, p300, _ = prize_ladder("mtt_300_players.json")
    P = bubble(dict(prizes=p300, players_left=46, avg_bb=20.0, table=(10.0,) * NSEAT))
    right = coach.solve(Spot((10.0,) * NSEAT, ante=1.0, ante_mode="bb"), method="cfr+",
                        target=0.001, check_every=25, max_iters=20_000, payouts=P)
    wrong = coach.solve(Spot((10.0,) * NSEAT), method="cfr+", target=0.001, check_every=25,
                        max_iters=20_000, payouts=P)

    u = uniforms(NHANDS, NSEAT, SEED)
    base = simulate(Spot((10.0,) * NSEAT, ante=1.0, ante_mode="bb"), right.tree,
                    {s: right.strategy for s in range(NSEAT)}, NHANDS, SEED, P, u=u)
    sig_hand = base.std(axis=0).max()
    eps_hand = Z * sig_hand / np.sqrt(LIFETIME)
    full = mix(1.0, right, wrong, NSEAT)[0]
    dtv1 = float((hands.PRIOR[None, :] * np.abs(
        right.strategy[:, :, 1] - full[:, :, 1])).sum(axis=1).max())
    print(f"sigma_hand {sig_hand:.4f}  eps_hand {eps_hand:.6f}  "
          f"(mICM/hand, bubble spot)")
    print(f"right = bb-ante 1.0, wrong = no ante; dTV at a=1 is {dtv1 * 100:.2f}%")

    print(f"\n{'a':>6} {'dTV':>7} {'loss max':>10} {'se':>7} {'sig_D':>7} {'eps_D':>9} "
          f"{'sigD/sigH':>10} {'loss/eps_D':>11}")
    for a in MIXES:
        st = mix(a, right, wrong, NSEAT)
        net = simulate(Spot((10.0,) * NSEAT, ante=1.0, ante_mode="bb"), right.tree, st, NHANDS,
                       SEED, P, u=u)
        d = base - net
        dtv = float((hands.PRIOR[None, :] * np.abs(
            right.strategy[:, :, 1] - st[0][:, :, 1])).sum(axis=1).max())
        assert abs(dtv - a * dtv1) < 1e-12, f"blend is not linear at a={a}"
        mean = d.mean(axis=0)
        se = d.std(axis=0) / np.sqrt(NHANDS)
        k = int(np.argmax(mean))
        sig_d = d.std(axis=0).max()
        eps_d = Z * sig_d / np.sqrt(LIFETIME)
        print(f"{a:>6.2f} {dtv * 100:>6.2f}% {mean[k]:>10.6f} {se[k]:>7.6f} {sig_d:>7.4f} "
              f"{eps_d:>9.6f} {sig_d / sig_hand:>10.4f} {mean[k] / eps_d:>10.1f}x")


if __name__ == "__main__":
    main()
