"""Does the sequential best response agree with pushfold/auditor.py where the old one is exact?

On a push/fold tree each seat acts at most once per path, so the old shortcut IS a best
response. Both must agree, per seat, in chip EV and in ICM. Anchor strategies first
(always-fold, always-jam, uniform), in the style of Johanson, Waugh, Bowling, Zinkevich,
*Accelerating Best Response Calculation in Large Extensive Games*, IJCAI 2011, Table 1.

Run: .venv/bin/python deepstack-swarm/workspace/johanson/check_against_auditor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seqbr  # noqa: E402
from pushfold import auditor, floor, hands, icm, icm_pricer  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

N = len(hands.CLASSES)
PAYOUTS = icm.Payouts(prizes=(50.0, 30.0, 20.0))


def strategies(shape, rng):
    yield "always-fold", np.tile([1.0, 0.0], shape[:2] + (1,))
    yield "always-jam", np.tile([0.0, 1.0], shape[:2] + (1,))
    yield "uniform-0.5", np.full(shape, 0.5)
    for i in range(2):
        r = rng.random(shape[:2] + (1,))
        yield f"random-{i}", np.concatenate([1 - r, r], axis=2)


def main() -> None:
    rng = np.random.default_rng(20260927)
    spots = [
        ("hu 10bb", Spot(stacks=(10.0, 10.0))),
        ("3-max 10bb", Spot(stacks=(10.0, 10.0, 10.0))),
        ("4-max 8/12/10/6", Spot(stacks=(8.0, 12.0, 10.0, 6.0))),
        ("6-max 15bb ante .125", Spot(stacks=(15.0,) * 6, ante=0.125)),
    ]
    worst_ev = worst_gain = 0.0
    for label, spot in spots:
        tree = floor.build(spot)
        game = seqbr.from_floor(tree)
        assert len(game.nodes) == len(tree.nodes) and len(game.endings) == len(tree.terminals)
        shape = (len(tree.nodes), N, 2)
        # ICM: 3 paid, with enough of a field that every spot has >= 4 players left.
        field = (10.0,) * max(0, 4 - spot.n)
        payout = icm.Payouts(prizes=PAYOUTS.prizes, field=field)
        for mode, payouts in (("chipEV", None), ("ICM", payout)):
            plans = icm_pricer.plans_for(tree, payouts)
            for name, sigma in strategies(shape, rng):
                old = auditor.audit(tree, sigma, plans, payouts)
                new = seqbr.audit(game, sigma, payouts)
                d_ev = float(np.abs(old.ev - new.ev).max())
                d_gain = float(np.abs(old.gain - new.gain).max())
                d_short = float(np.abs(new.shortcut - new.gain).max())
                worst_ev, worst_gain = max(worst_ev, d_ev), max(worst_gain, d_gain)
                print(f"{label:<22} {mode:<7} {name:<12} "
                      f"expl_old={old.exploitability: .6f} expl_new={new.exploitability: .6f} "
                      f"dEV={d_ev:.2e} dGAIN={d_gain:.2e} short-exact={d_short:.2e}")
    print(f"\nworst |EV difference| over all cases: {worst_ev:.3e}")
    print(f"worst |gain difference| over all cases: {worst_gain:.3e}")
    # Tolerance: chip EV and heads-up ICM agree to 1e-14. The residual at 3+ seats with ICM is
    # float32 rounding in icm_pricer's 3-way path (`orders()` is float32 and the group weights
    # are cast to float32 before the product); see float32_vs_float64 below.
    assert worst_ev < 1e-5 and worst_gain < 1e-5, "the two auditors disagree"
    print("PASS: independent sequential BR reproduces pushfold/auditor.py on push/fold.")
    float32_vs_float64()


def float32_vs_float64() -> None:
    """How much of the 3-way ICM residual is float32? Re-run one case in float64 tables."""
    spot = Spot(stacks=(10.0, 10.0, 10.0))
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(10.0,))
    tree, game = floor.build(spot), None
    game = seqbr.from_floor(tree)
    sigma = np.full((len(tree.nodes), N, 2), 0.5)
    t = seqbr.tables()
    wide = seqbr.Leaf(t.e2.astype(np.float64), t.eq3.astype(np.float64),
                      t.pw.astype(np.float64), t.orders.astype(np.float64))
    narrow = seqbr.Leaf(t.e2.astype(np.float32), t.eq3.astype(np.float32),
                        t.pw.astype(np.float32), t.orders.astype(np.float32))
    a = seqbr.audit(game, sigma, payouts, wide)
    b = seqbr.audit(game, sigma, payouts, narrow)
    old = auditor.audit(tree, sigma, icm_pricer.plans_for(tree, payouts), payouts).exploitability
    print(f"3-max ICM uniform: float64 tables {a.exploitability:.9f}, float32 {b.exploitability:.9f}, "
          f"pushfold {old:.9f}  (ICM chips/hand)")


if __name__ == "__main__":
    main()
