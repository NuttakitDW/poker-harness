"""Where do my per-ending ICM values and icm_pricer's disagree? Collapse mine onto their columns."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seqbr  # noqa: E402
from pushfold import floor, hands, icm, icm_pricer, pricer  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

N = len(hands.CLASSES)
spot = Spot(stacks=(10.0, 10.0, 10.0))
payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,))
tree = floor.build(spot)
game = seqbr.from_floor(tree)
sigma = np.full((len(tree.nodes), N, 2), 0.5)
plans = icm_pricer.plan(tree, payouts)
cols = pricer.columns(sigma)
U = seqbr.values(game, sigma, payouts)

for seat in range(spot.n):
    p = plans[seat]
    cfv, fixed = p.price(cols)
    local = {g: i for i, g in enumerate(p.nodes.tolist())}
    mine_cfv = np.zeros_like(cfv)
    mine_fixed = np.zeros(N)
    for z in tree.terminals:
        u = U[seat, :, z.index]
        if z.nodes[seat] < 0:
            mine_fixed += u
        else:
            mine_cfv[local[z.nodes[seat]], :, z.actions[seat]] += u
    dc = np.abs(mine_cfv - cfv).max()
    df = np.abs(mine_fixed - fixed).max()
    print(f"seat {seat}: max |dcfv| = {dc:.3e}   max |dfixed| = {df:.3e}")
    if df > 1e-9:
        bad = np.argmax(np.abs(mine_fixed - fixed))
        print(f"   worst class {hands.CLASSES[bad]}: mine={mine_fixed[bad]:.6f} theirs={fixed[bad]:.6f}")
        # which endings have no decision for this seat?
        for z in tree.terminals:
            if z.nodes[seat] < 0:
                print("   no-decision ending", z.index, z.actions, "alive", z.alive,
                      f"u[{hands.CLASSES[bad]}]={U[seat, bad, z.index]:.6f}")
    if dc > 1e-9:
        idx = np.unravel_index(np.argmax(np.abs(mine_cfv - cfv)), cfv.shape)
        print(f"   worst cell node_local={idx[0]} class={hands.CLASSES[idx[1]]} action={idx[2]}: "
              f"mine={mine_cfv[idx]:.6f} theirs={cfv[idx]:.6f}")
        for z in tree.terminals:
            if z.nodes[seat] >= 0 and local[z.nodes[seat]] == idx[0] and z.actions[seat] == idx[2]:
                print("   contributing ending", z.index, z.actions, "alive", z.alive,
                      f"u={U[seat, idx[1], z.index]:.6f}")
