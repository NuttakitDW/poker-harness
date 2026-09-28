"""How much a flop leaf's *shape* matters: distribution over stacks vs scalar chip EV, and sigma.

One spot, one decision: 3-handed final table, 25bb each, BTN opens to 2.2, SB folds, BB decides
between fold and flat call. The call reaches a flop, which is priced three ways:

  dist  sigma=0  L0 checkdown, priced as a distribution over final stacks (correct shape)
  flat  sigma=0  the same checkdown collapsed to expected chips, then priced once (wrong shape)
  dist  sigma=1  L0-max: every chip two alive seats can match goes in, priced as a distribution

The number reported is the PRIOR-weighted share of hands the BB calls with, when it calls iff
call beats fold. It is a leaf-pricing comparison against a fixed opener range, not a solve.

Run: .venv/bin/python deepstack-swarm/workspace/moravcik/flop_leaf_demo.py
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pushfold import hands, icm, oddsmaker  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import leaf  # noqa: E402

OPEN = 2.2
BTN, SB, BB = 0, 1, 2


def opener_range(share: float) -> np.ndarray:
    """Top `share` of hands by equity against a random hand, PRIOR-weighted, as a range vector."""
    e2 = oddsmaker.two_way()
    strength = e2 @ hands.PRIOR
    order = np.argsort(-strength)
    weight = hands.PRIOR[order].cumsum()
    keep = np.zeros(len(strength))
    keep[order[weight <= share]] = 1.0
    return keep


def bb_values(spot: Spot, payouts, sigma: float, flat: bool, opens: np.ndarray):
    """ICM value to the BB of calling, per hand class, against the opener's range."""
    e2 = oddsmaker.two_way()
    call = leaf.stackoff(spot, leaf.Ending((BTN, BB), (OPEN, spot.sb, OPEN)), sigma)
    fold = leaf.Ending((BTN,), (OPEN, spot.sb, spot.bb))
    chips = leaf.worth(spot, [call, fold], None)
    if flat:
        # collapse to expected chips first, then price: the mistake this experiment is about.
        mix = (e2[:, :, None] * chips[0][(BB, BTN)][None, None, :]
               + (1 - e2)[:, :, None] * chips[0][(BTN, BB)][None, None, :])
        before = icm.value(np.array([spot.stacks]), spot.stacks, payouts)[0]
        final = np.array(spot.stacks)[None, None, :] + mix
        priced = icm.value(final.reshape(-1, spot.n), spot.stacks, payouts) - before
        v_call = priced.reshape(len(e2), len(e2), spot.n)[:, :, BB]
    else:
        w = leaf.worth(spot, [call, fold], payouts)
        lose, win = w[0][(BTN, BB)][BB], w[0][(BB, BTN)][BB]
        v_call = lose + (win - lose) * e2
    prior = hands.PRIOR * opens
    prior = prior / prior.sum()
    v_fold = leaf.worth(spot, [call, fold], payouts)[1][(BTN,)][BB]
    return v_call @ prior, v_fold


def run(spot: Spot, payouts, label: str, share: float = 0.45) -> None:
    opens = opener_range(share)
    print(f"\n{label}: stacks {spot.stacks}, BTN opens {OPEN}bb with the top "
          f"{100 * (hands.PRIOR * opens).sum():.0f}% of hands, BB faces it")
    print(f"{'leaf':<26}{'BB call range':>14}{'best hand gain':>16}{'avg over range':>16}")
    rows = {}
    for label2, sigma, flat in (("dist  sigma=0  (L0)", 0.0, False),
                                ("flat  sigma=0  (chip EV)", 0.0, True),
                                ("dist  sigma=1  (L0-max)", 1.0, False)):
        v_call, v_fold = bb_values(spot, payouts, sigma, flat, opens)
        edge = v_call - v_fold
        pct = 100 * hands.PRIOR @ (edge > 0)
        print(f"{label2:<26}{pct:>13.1f}%{edge.max():>16.4f}{hands.PRIOR @ edge:>16.4f}")
        rows[label2] = edge
    gap = rows["flat  sigma=0  (chip EV)"] - rows["dist  sigma=0  (L0)"]
    print(f"  chip-EV leaf minus L0, per hand: max {gap.max():+.4f}, min {gap.min():+.4f}, "
          f"mean {hands.PRIOR @ gap:+.4f} ICM chips")
    band = rows["dist  sigma=0  (L0)"] - rows["dist  sigma=1  (L0-max)"]
    print(f"  L0 minus L0-max, per hand:      max {band.max():+.4f}, min {band.min():+.4f}, "
          f"mean {hands.PRIOR @ band:+.4f} ICM chips")


def sweep(spot: Spot, payouts, label: str, share: float = 0.45) -> None:
    """BB call range as sigma grows: how tight must a leaf model be for the chart to hold still."""
    opens = opener_range(share)
    e2 = oddsmaker.two_way()
    worst = (e2 * (hands.PRIOR * opens)).sum(axis=1) / (hands.PRIOR * opens).sum()
    print(f"\n{label}: sigma sweep. Worst class equity vs the opener's range: "
          f"{worst.min():.3f} (needs {1.2 / 4.9:.3f} to call a checkdown)")
    print(f"{'sigma':>7}{'call range (dist)':>20}{'call range (flat)':>20}"
          f"{'flat - dist, mean':>20}")
    for sigma in (0.0, 0.1, 0.25, 0.5, 1.0):
        out = []
        for flat in (False, True):
            v_call, v_fold = bb_values(spot, payouts, sigma, flat, opens)
            out.append(v_call - v_fold)
        print(f"{sigma:>7.2f}{100 * hands.PRIOR @ (out[0] > 0):>19.1f}%"
              f"{100 * hands.PRIOR @ (out[1] > 0):>19.1f}%"
              f"{hands.PRIOR @ (out[1] - out[0]):>20.4f}")


if __name__ == "__main__":
    ft = icm.Payouts((50, 30, 20))
    run(Spot((25, 25, 25)), ft, "3-handed final table, flat prizes")
    run(Spot((25, 25, 25)), icm.Payouts((1,)), "3-handed, winner-take-all (= chip EV)")
    run(Spot((15, 15, 15)), ft, "3-handed final table, 15bb")
    run(Spot((25, 25, 25)), icm.Payouts((50, 30, 20), field=(25.0,) * 6), "9 left, 3 at the table")
    sweep(Spot((25, 25, 25)), ft, "3-handed final table, 25bb")
    sweep(Spot((15, 15, 15)), ft, "3-handed final table, 15bb")
