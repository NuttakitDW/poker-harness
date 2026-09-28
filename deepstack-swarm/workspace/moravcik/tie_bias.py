"""Ties are coin flips in oddsmaker.orders(); under concave ICM a chop is worth more than that.

pushfold/oddsmaker.py:238-241: "Ties count as coin flips." The pricer therefore replaces the
chopped pot (both seats take half) with a lottery over two whole pots. ICM is concave, so the
lottery is worth strictly less to both. This measures the error on the existing push/fold game,
where it is largest, and on a 2.2bb flop leaf, where it is not.

Run: .venv/bin/python deepstack-swarm/workspace/moravcik/tie_bias.py
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pushfold import hands, icm, oddsmaker  # noqa: E402
from pushfold.spot import Spot  # noqa: E402


def tie_rate(deals: int = 200_000, seed: int = 7) -> float:
    """Chance two random hold'em hands tie on a random five-card board, by Monte Carlo."""
    rng = np.random.default_rng(seed)
    ties = 0
    done = 0
    while done < deals:
        n = min(50_000, deals - done)
        cards = np.stack([rng.permutation(52)[:9] for _ in range(n)])
        s = oddsmaker.strength(cards[:, 0:2], cards[:, 4:9])
        t = oddsmaker.strength(cards[:, 2:4], cards[:, 4:9])
        ties += int((s == t).sum())
        done += n
    return ties / deals


def gap(spot: Spot, payouts, each: float, dead: float, seats=(0, 2)) -> tuple[float, float]:
    """ICM chips lost per tied pot by pricing a chop as a coin flip, for each of the two seats.

    The two seats each put in `each`; `dead` is money from the seats who folded. Pot = 2*each+dead.
    """
    a, b = seats
    pot = 2 * each + dead
    rest = [s for s in range(spot.n) if s not in seats]
    paid = np.zeros(spot.n)
    paid[a] = paid[b] = each
    for s in rest:
        paid[s] = dead / max(len(rest), 1)
    left = np.array(spot.stacks) - paid
    chop = left.copy()
    chop[[a, b]] += pot / 2
    a_wins, b_wins = left.copy(), left.copy()
    a_wins[a] += pot
    b_wins[b] += pot
    rows = icm.value(np.array([chop, a_wins, b_wins]), spot.stacks, payouts)
    flip = 0.5 * (rows[1] + rows[2])
    return float(rows[0][a] - flip[a]), float(rows[0][b] - flip[b])


if __name__ == "__main__":
    ft = icm.Payouts((50, 30, 20))
    print("3-handed final table, 25/25/25, flat prizes (50/30/20)")
    for each, dead, what in ((2.2, 0.5, "flop leaf after a 2.2bb open, called"),
                             (8.0, 0.5, "an 8bb vs 8bb all-in"),
                             (25.0, 0.5, "a 25bb vs 25bb all-in")):
        loss = gap(Spot((25, 25, 25)), ft, each, dead)
        print(f"  pot {2 * each + dead:>5.1f}bb  {what:<38} chop - coinflip = "
              f"{loss[0]:+.4f} / {loss[1]:+.4f} ICM chips per tied pot")
    rate = tie_rate()
    print(f"\nTwo random hands tie on a random board {100 * rate:.2f}% of the time "
          "(200k deals, oddsmaker.strength).")
    loss = gap(Spot((25, 25, 25)), ft, 25.0, 0.5)
    print(f"So a 25bb all-in showdown is mispriced by about {rate * loss[0]:+.4f} ICM chips "
          "per showdown,\nand the flop leaf by "
          f"{rate * gap(Spot((25, 25, 25)), ft, 2.2, 0.5)[0]:+.5f}.")
