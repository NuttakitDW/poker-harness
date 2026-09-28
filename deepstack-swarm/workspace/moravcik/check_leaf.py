"""Regression: the generalised leaf must reproduce pushfold exactly where they overlap.

Two claims, both exact (float equality up to 1e-12):
  1. settle(spot, Ending(alive, contributions(spot, jammers))) == cashier.settle(spot, jammers)
     for every terminal of every push/fold tree below.
  2. worth(...) == icm_pricer._worth(...) for the same trees under real payouts.

A checkdown at SPR = 0 *is* an all-in, so this also anchors the leaf: where L0 has no error
by construction, it must give pushfold's numbers back.

Run: .venv/bin/python deepstack-swarm/workspace/moravcik/check_leaf.py
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pushfold import cashier, floor, icm, icm_pricer  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import leaf  # noqa: E402

SPOTS = (
    Spot((10, 10)),
    Spot((4, 25)),
    Spot((10, 10, 10)),
    Spot((3, 10, 20)),                              # side pot
    Spot((5, 12, 8, 20), ante=0.125),
    Spot((1.5,) * 5, ante=1.0, ante_mode="bb"),     # BB all-in by posting
    Spot((6, 9, 14, 4, 11, 7), ante=0.1),
    Spot((8, 12, 20), fee=0.2),                     # GG AoF style fee
)
PAYOUTS = icm.Payouts((50, 30, 20), field=(15.0, 22.0))


def main() -> int:
    bad = 0
    for spot in SPOTS:
        tree = floor.build(spot)
        endings = leaf.from_pushfold(tree)
        for z, e in zip(tree.terminals, endings):
            want, got = cashier.settle(spot, z.jammers), leaf.settle(spot, e)
            if not np.allclose(want.fixed, got.fixed, atol=1e-12) or want.layers != got.layers:
                bad += 1
                print(f"  settle mismatch {spot.stacks} {z.actions}\n    {want}\n    {got}")
        want_worth = icm_pricer._worth(tree, PAYOUTS)
        got_worth = leaf.worth(spot, endings, PAYOUTS)
        for i, (w, g) in enumerate(zip(want_worth, got_worth)):
            if set(w) != set(g) or any(not np.allclose(w[k], g[k], atol=1e-12) for k in w):
                bad += 1
                print(f"  worth mismatch {spot.stacks} terminal {i}")
        chips = leaf.worth(spot, endings, None)
        for z, g in zip(tree.terminals, chips):
            s = cashier.settle(spot, z.jammers)
            for order, row in g.items():
                want = s.net_for({seat: p + 1 for p, seat in enumerate(order)})
                if not np.allclose(want, row, atol=1e-12):
                    bad += 1
                    print(f"  chip mismatch {spot.stacks} {order}")
        print(f"ok  {spot.n}-handed {spot.stacks} fee={spot.fee}  "
              f"{len(tree.terminals)} endings")

    # sigma = 1 on a push/fold ending must be a no-op: everyone is already all-in.
    for spot in SPOTS:
        tree = floor.build(spot)
        for e in leaf.from_pushfold(tree):
            if leaf.stackoff(spot, e, 1.0) != e:
                bad += 1
                print(f"  sigma=1 changed an all-in ending: {spot.stacks} {e}")
    print("sigma=1 is a no-op on all-in endings: ok" if not bad else "")
    print(f"\n{'PASS' if not bad else str(bad) + ' FAILURES'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
