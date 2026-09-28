"""What does a chart difference COST, in the same units as the lifetime epsilon?

bard's scenario grid (workspace/findings/bard-scenario-grid.md) measures how far apart two
charts are in combo-weighted total variation (dTV) and flags "needs its own axis" against an
illustrative 2% line. The lifetime epsilon is in value units (ICM chips or bb per hand), so the
two are not comparable until someone measures the exchange rate. This script measures it.

Method. Solve the two configurations of one axis in the same spot (same tree shape). Then play
the wrong chart: every seat plays the stale chart at the true spot's pricing, and compare with
every seat playing the chart solved for that spot. The difference is the value cost of the
axis, in the same units as the epsilon. Because dTV is linear in a mixture of two charts, the
interpolated charts sigma_a = (1-a) chart_right + a chart_wrong also give the local slope,
epsilon-sized value change per point of dTV.
"""
from __future__ import annotations

import json

import numpy as np

from pushfold import auditor, coach, floor, hands, icm
from pushfold.spot import Spot

from lifetime_eps import LIFETIME, Z, bubble, describe, prize_ladder, simulate, uniforms

JAM = floor.JAM


def solve(spot, payouts, target=0.001, max_iters=20_000):
    return coach.solve(spot, method="cfr+", target=target, check_every=25, max_iters=max_iters,
                       payouts=payouts)


def dtv(a: coach.Result, b: coach.Result) -> tuple[float, int]:
    """Per-node combo-weighted TV distance between two charts; returns (max, argmax node)."""
    pa, pb = a.strategy[:, :, JAM], b.strategy[:, :, JAM]
    per = (hands.PRIOR[None, :] * np.abs(pa - pb)).sum(axis=1)
    return float(per.max()), int(per.argmax())


def node_label(result: coach.Result, index: int) -> str:
    nd = result.tree.nodes[index]
    history = "".join("f" if x == floor.FOLD else "J" for x in nd.history) or "-"
    return f"{result.spot.names[nd.seat]}|{history}"


def report(axis: str, right: coach.Result, wrong: coach.Result, payouts, eps: float,
           alphas=(0.0, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0), n_hands=200_000,
           seed=20260927) -> dict:
    """Value of the chart interpolated from `right` (a=0) toward `wrong` (a=1), at right's spot.

    The paired block answers the merge question: chart `wrong` and chart `right` are played at
    the same spot on the same deals with the same action draws, so the per-hand difference is a
    paired comparison and its own standard deviation says how many hands it takes to tell the
    two charts apart in value.
    """
    d, where = dtv(right, wrong)
    base = auditor.audit(right.tree, right.strategy, payouts=payouts)
    rows = []
    for a in alphas:
        sigma = (1.0 - a) * right.strategy + a * wrong.strategy
        rep = auditor.audit(right.tree, sigma, payouts=payouts)
        loss = base.ev - rep.ev                      # per seat, positive = worse
        rows.append(dict(alpha=a, dtv=a * d, ev=[float(v) for v in rep.ev],
                         loss=[float(v) for v in loss], loss_max=float(loss.max()),
                         loss_mean=float(loss.mean()), exploit=rep.exploitability))
    # local slope: (value lost) per point of dTV, from the smallest non-zero mixture
    small = rows[1]
    slope = small["loss_mean"] / small["dtv"] if small["dtv"] > 0 else float("inf")

    # paired comparison of the two charts at the right chart's spot
    n = right.spot.n
    u = uniforms(n_hands, n, seed)
    net_r = simulate(right.spot, right.tree, {s: right.strategy for s in range(n)}, n_hands,
                     seed, payouts, u=u)
    net_w = simulate(right.spot, right.tree, {s: wrong.strategy for s in range(n)}, n_hands,
                     seed, payouts, u=u)
    diff = net_w - net_r
    sigma_diff = float(diff.std(axis=0).max())
    mean_diff = float(diff.mean(axis=0).max())
    pair_eps = Z * sigma_diff / np.sqrt(LIFETIME)
    paired = dict(paired=True, sigma_diff=sigma_diff, mean_diff=mean_diff, pair_eps=pair_eps,
                  sigma_right=float(net_r.std(axis=0).max()))
    print(f"\n--- axis: {axis}")
    print(f"    dTV max {d * 100:.2f}% at {node_label(right, where)}; "
          f"epsilon = {eps:.6f} (units/hand)")
    print(f"    exploitability of the right chart {base.exploitability:.5f}, "
          f"of the wrong chart in this spot "
          f"{auditor.audit(right.tree, wrong.strategy, payouts=payouts).exploitability:.5f}")
    print(f"    {'mix a':>6} {'dTV':>7} {'max seat loss':>13} {'mean loss':>10} {'x eps':>7} "
          f"{'exploit':>9}")
    for r in rows:
        print(f"    {r['alpha']:>6.2f} {r['dtv'] * 100:>6.2f}% {r['loss_max']:>13.6f} "
              f"{r['loss_mean']:>10.6f} {r['loss_max'] / eps:>7.1f} {r['exploit']:>9.5f}")
    print(f"    local slope: {slope * 1000:.4f} m-units/hand per point of dTV "
          f"-> a value change of eps is {eps / slope * 100:.3f} points of dTV")
    print(f"    paired: mean loss {mean_diff:.6f}/hand, sd of the per-hand difference "
          f"{sigma_diff:.4f} (vs {paired['sigma_right']:.4f} for the right chart alone)")
    print(f"    paired epsilon {pair_eps:.6f} -> a lifetime of play separates the two charts "
          f"by {mean_diff / pair_eps:.1f}x")
    return dict(axis=axis, dtv=d, node=node_label(right, where), eps=eps, slope=slope,
                dtv_at_eps=eps / slope, rows=rows,
                exploit_right=base.exploitability,
                exploit_wrong=auditor.audit(right.tree, wrong.strategy,
                                            payouts=payouts).exploitability,
                paired=paired, eps_pair_value=pair_eps)


def main() -> None:
    _, p300, _ = prize_ladder("mtt_300_players.json")
    table6 = (10.0,) * 6
    P = bubble(dict(prizes=p300, players_left=46, avg_bb=20.0, table=table6))

    configs = {
        "no ante": Spot(table6, ante=0.0, ante_mode="bb"),
        "bb-ante 1.0": Spot(table6, ante=1.0, ante_mode="bb"),
        "each-ante 1/6": Spot(table6, ante=1.0 / 6.0, ante_mode="each"),
    }
    results, eps = {}, {}
    for name, sp in configs.items():
        r = solve(sp, P)
        net = simulate(sp, r.tree, {s: r.strategy for s in range(sp.n)}, 200_000, 20260927, P)
        per = describe(net)
        eps[name] = Z * max(p["sigma"] for p in per) / np.sqrt(LIFETIME)
        print(f"{name:<15} iters {r.iterations:>4} exploit {r.exploitability:.5f} "
              f"sigma_max {max(p['sigma'] for p in per):.4f} eps {eps[name]:.6f}")
        results[name] = r

    out = []
    # axis A: ante size, same mode -- both directions
    out.append(report("ante size at the bubble: bb-ante 1.0 (right) vs no ante (wrong)",
                      results["bb-ante 1.0"], results["no ante"], P, eps["bb-ante 1.0"]))
    out.append(report("ante size the other way: no ante (right) vs bb-ante 1.0 (wrong)",
                      results["no ante"], results["bb-ante 1.0"], P, eps["no ante"]))
    # axis B: ante mode at matched total money posted (bb 1.0 == each 1/6)
    out.append(report("ante mode at matched total: bb-ante 1.0 (right) vs each-ante 1/6 (wrong)",
                      results["bb-ante 1.0"], results["each-ante 1/6"], P, eps["bb-ante 1.0"]))

    with open("deepstack-swarm/workspace/davis/chart_cost.json", "w") as fh:
        json.dump(dict(eps=eps, reports=out), fh, indent=1)
    print("\nwrote deepstack-swarm/workspace/davis/chart_cost.json")


if __name__ == "__main__":
    main()
