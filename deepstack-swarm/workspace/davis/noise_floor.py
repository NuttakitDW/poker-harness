"""How much of the answer is the 3-way Monte Carlo table rather than the game?

pushfold/oddsmaker.py builds eq3 and pw by sampling SAMPLES=2000 random deals per class
triple (SEED 20260924). Every solve above 2 players is priced with those tables, so its
"exploitability" is measured against them, not against the true game.

alt_tables.py built the same tables a second time with different seeds. Two independent
2000-deal estimates differ by the noise of both, so Var(diff)/2 estimates Var(table), and
re-solving and re-auditing a spot on the second table measures what that noise does to the
number we report as exploitability, EV, chart and per-hand sigma. Nothing in pushfold/ is
edited: the module's cached table function is rebound for the duration of the run.
"""
from __future__ import annotations

import json

import numpy as np

from pushfold import auditor, coach, hands, icm, icm_pricer, oddsmaker, pricer
from pushfold.spot import Spot

from lifetime_eps import LIFETIME, Z, bubble, describe, prize_ladder, simulate

ALT = "deepstack-swarm/workspace/davis/e3-alt.npz"


def use(tables: oddsmaker.Tables) -> None:
    """Point every consumer at these tables (module-level rebind + cache clear)."""
    oddsmaker.three_way = lambda: tables
    pricer._three_way.cache_clear()
    pricer._two_way.cache_clear()
    oddsmaker.orders.cache_clear()
    icm_pricer._layouts.cache_clear()
    icm_pricer._pair.cache_clear()


def main() -> None:
    base = oddsmaker.three_way()
    alt = np.load(ALT)
    eq3, pw = alt["eq3"], alt["pw"]
    possible = base.possible
    assert bool((alt["possible"] == possible).all()), "the two builds disagree on feasibility"
    for name, a, b in (("eq3", eq3, base.eq3), ("pw", pw, base.pw)):
        d = (a - b)[possible]
        print(f"{name}: {len(d):,} possible triples, rms(diff) {np.sqrt((d ** 2).mean()):.5f}, "
              f"max|diff| {np.abs(d).max():.5f}, implied per-table sigma "
              f"{np.sqrt((d ** 2).mean() / 2):.5f}")
    tables_alt = oddsmaker.Tables(base.e2, eq3, pw, base.possible, int(alt["samples"]))

    _, p300, _ = prize_ladder("mtt_300_players.json")
    table6 = (10.0,) * 6
    P = bubble(dict(prizes=p300, players_left=46, avg_bb=20.0, table=table6))
    spots = {"6h-10bb-ante1.0-bb (chipEV)": (Spot(table6, ante=1.0, ante_mode="bb"), None),
             "6h-10bb-ante1.0-bb-bubble46 (ICM)": (Spot(table6, ante=1.0, ante_mode="bb"), P),
             "HU-10bb (chipEV, exact e2 only)": (Spot((10.0, 10.0)), None)}

    out = []
    for label, (spot, payouts) in spots.items():
        use(base)
        r1 = coach.solve(spot, method="cfr+", target=0.001, check_every=25, max_iters=20_000,
                         payouts=payouts)
        a1 = auditor.audit(r1.tree, r1.strategy, payouts=payouts)
        use(tables_alt)
        r2 = coach.solve(spot, method="cfr+", target=0.001, check_every=25, max_iters=20_000,
                         payouts=payouts)
        a2 = auditor.audit(r2.tree, r2.strategy, payouts=payouts)
        # each chart audited in the other's model: what a chart tuned to one table loses on the other
        use(tables_alt)
        cross_a = auditor.audit(r2.tree, r1.strategy, payouts=payouts)   # chart 1 under table 2
        use(base)
        cross_b = auditor.audit(r1.tree, r2.strategy, payouts=payouts)   # chart 2 under table 1
        d = np.abs(r1.strategy[:, :, 1] - r2.strategy[:, :, 1])
        dtv = float((hands.PRIOR[None, :] * d).sum(axis=1).max())
        net = simulate(spot, r1.tree, {s: r1.strategy for s in range(spot.n)}, 200_000, 20260927,
                       payouts)
        per = describe(net)
        sigma = max(p["sigma"] for p in per)
        print(f"\n=== {label}")
        print(f"    exploit: table A {r1.exploitability:.5f} (iters {r1.iterations}), "
              f"table B {r2.exploitability:.5f} (iters {r2.iterations}), "
              f"chart dTV {dtv * 100:.2f}%")
        print(f"    EV table A  {np.round(a1.ev, 4)}")
        print(f"    EV table B  {np.round(a2.ev, 4)}")
        print(f"    |dEV| per seat {np.round(np.abs(a1.ev - a2.ev), 4)} "
              f"max {np.abs(a1.ev - a2.ev).max():.5f}")
        print(f"    chart A audited on table B: EV {np.round(cross_a.ev, 4)} "
              f"(loss {np.round(cross_a.ev - a1.ev, 4)})")
        print(f"    chart B audited on table A: EV {np.round(cross_b.ev, 4)} "
              f"(loss {np.round(cross_b.ev - a2.ev, 4)})")
        print(f"    sigma_max {sigma:.4f}, eps {Z * sigma / np.sqrt(LIFETIME):.6f}")
        out.append(dict(label=label, exploit_A=r1.exploitability, exploit_B=r2.exploitability,
                        dtv=dtv, ev_A=[float(v) for v in a1.ev], ev_B=[float(v) for v in a2.ev],
                        cross_loss_A_on_B=[float(v) for v in (cross_a.ev - a1.ev)],
                        cross_loss_B_on_A=[float(v) for v in (cross_b.ev - a2.ev)],
                        sigma_max=sigma, eps=Z * sigma / np.sqrt(LIFETIME)))
    with open("deepstack-swarm/workspace/davis/noise_floor.json", "w") as fh:
        json.dump(out, fh, indent=1)
    print("\nwrote deepstack-swarm/workspace/davis/noise_floor.json")


if __name__ == "__main__":
    main()
