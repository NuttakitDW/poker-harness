"""A/B: Tier 1 as-is (FLOP terminals priced by the L0 checkdown) vs leaf-free (behind_cap=1).

Usage:
  .venv/bin/python ab.py <spot> <mode> <target> [max_iters]
     spot: 3max | 6max | ladder | 2short
     mode: chip | icm
Writes a json record next to this file.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/burch/open3bet"))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/bowling/tier1chart"))

from pushfold import hands, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import floor3  # noqa: E402
import solve3  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reach as R  # noqa: E402

SPOTS = {
    "3max": (5.0, 15.0, 30.0),
    "6max": (4.0, 8.0, 15.0, 20.0, 30.0, 15.0),
    "ladder": (5.0, 10.0, 15.0, 20.0, 25.0, 30.0),
    "2short": (2.0, 15.0, 15.0, 15.0, 15.0, 15.0),
    "3max-eq": (15.0, 15.0, 15.0),
}


LEFT = 46          # "small" MTT (300 runners, 45 paid) at the bubble: paid + 1


def payouts_for(stacks: tuple[float, ...], left: int) -> icm.Payouts:
    """'small' MTT (300 runners, 45 paid) at `left` players left, table = len(stacks).

    The players away from the table are one crowd at the table's mean stack -- a modelling
    choice, stated, and identical in every arm of the A/B.
    """
    import scenarios as S
    return icm.Payouts(prizes=S.prizes("small"), crowd=left - len(stacks),
                       crowd_stack=float(np.mean(stacks)))


def stackoff(tree: floor3.Tree, sigma_dial: float = 1.0) -> floor3.Tree:
    """FLOP terminals priced by moravcik's sigma dial at 1: every chip two alive seats can still
    match goes in (leaf-model-L0.md Sec 4, `leaf.stackoff`). sigma=0 is the L0 checkdown the
    as-is tree already uses; this is the other, exactly-computable end of that one axis. The
    action set is untouched, so this arm isolates *pricing* from the action restriction."""
    spot = tree.spot
    out = []
    for z in tree.terminals:
        if z.kind != floor3.FLOP:
            out.append(z)
            continue
        behind = sorted((spot.stacks[s] - spot.antes[s] - z.invested[s] for s in z.live),
                        reverse=True)
        room = behind[1] if len(behind) > 1 else 0.0
        extra = [sigma_dial * min(max(spot.stacks[s] - spot.antes[s] - z.invested[s], 0.0), room)
                 if s in z.live else 0.0 for s in range(spot.n)]
        out.append(dataclasses.replace(z, invested=tuple(a + b for a, b in
                                                         zip(z.invested, extra))))
    return dataclasses.replace(tree, terminals=tuple(out))


def solve_arm(stacks, tier1_kw, mode, target, max_iters, check_every=25, dial=None):
    spot = Spot(stacks=stacks)
    tree = floor3.build(spot, tier1=True, **tier1_kw)
    if dial is not None:
        tree = stackoff(tree, dial)
    pay = payouts_for(stacks, LEFT) if mode == "icm" else None
    t0 = time.perf_counter()
    if mode == "chip":
        sol = solve3.solve(tree, target, "cfr+", check_every=check_every, max_iters=max_iters)
    else:
        sol = solve3.solve_icm(tree, pay, target, "cfr+", check_every=check_every,
                               max_iters=max_iters)
    sigma = sol.st.average()
    return dict(tree=tree, sigma=sigma, sol=sol, pay=pay, seconds=time.perf_counter() - t0)


def node_key(nd) -> tuple:
    return (nd.seat, tuple(nd.actions), nd.history)


def compare(a, b) -> dict:
    """Chart diff over nodes present in both arms, matched by (seat, actions, history)."""
    ka = {node_key(nd): nd.index for nd in a["tree"].nodes}
    diffs = []
    for nd in b["tree"].nodes:
        i = ka.get(node_key(nd))
        if i is None:
            continue
        sa = a["sigma"][i, :, :len(nd.actions)]
        sb = b["sigma"][nd.index, :, :len(nd.actions)]
        w = hands.PRIOR[:, None]
        diffs.append((float((w * np.abs(sa - sb)).sum() / len(nd.actions)),
                      float(np.abs(sa - sb).max())))
    return {"matched_nodes": len(diffs),
            "mean_abs_dsigma_prior": float(np.mean([d[0] for d in diffs])) if diffs else 0.0,
            "max_abs_dsigma": float(max(d[1] for d in diffs)) if diffs else 0.0}


def range_at(tree, sigma, node_index, label: str) -> dict:
    nd = tree.nodes[node_index]
    acts = R.node_action_range(tree, sigma, node_index)
    # classes where the given action is the majority choice, PRIOR-weighted
    out = {f"P({k})": round(v, 4) for k, v in acts.items()}
    for k, a in enumerate(nd.actions):
        col = sigma[node_index, :, k]
        out[f"range_{floor3.ACTION_NAMES[a]}"] = round(
            float(hands.PRIOR[col > 0.5].sum()), 4)
    return out


def main() -> None:
    name, mode = sys.argv[1], sys.argv[2]
    target = float(sys.argv[3])
    max_iters = int(sys.argv[4]) if len(sys.argv) > 4 else 20000
    stacks = SPOTS[name]
    rec: dict = {"spot": name, "stacks": stacks, "mode": mode, "target": target}
    arms, solved = {}, {}
    all_arms = {"asis": ({}, None), "leafree": ({"behind_cap": 1}, None),
                "stackoff": ({}, 1.0)}
    wanted = sys.argv[5].split(",") if len(sys.argv) > 5 else ["asis", "leafree"]
    for arm in wanted:
        kw, dial = all_arms[arm]
        r = solve_arm(stacks, kw, mode, target, max_iters, dial=dial)
        solved[arm] = r
        tree, sigma, sol = r["tree"], r["sigma"], r["sol"]
        kr = R.kind_reach(tree, sigma)
        p = R.terminal_reach(tree, sigma)
        flop_terms = [(z.index, float(p[z.index])) for z in tree.terminals
                      if z.kind == floor3.FLOP]
        ar = {"nodes": len(tree.nodes), "terminals": len(tree.terminals),
              "counts": tree.counts(), "converged": sol.converged,
              "iters": sol.history[-1][0], "final_gain": sol.history[-1][1],
              "seconds": round(sol.seconds, 2), "kind_reach": {k: round(v, 6) for k, v in kr.items()},
              "reach_sum": round(float(p.sum()), 6),
              "flop_terminal_reach": [(i, round(v, 8)) for i, v in flop_terms],
              "flop_reach_total": round(sum(v for _, v in flop_terms), 8),
              "history": [[it, g] for it, g in sol.history[-6:]]}
        # the short stack's first-to-act node (it is seat 0 in every spot here)
        first = [nd for nd in tree.nodes if nd.seat == 0 and not nd.history]
        if first:
            n0 = first[0].index
            ar["short_firstin"] = range_at(tree, sigma, n0, "first-in")
            # kind reach *conditional* on the short seat's action at n0: pin it, re-measure.
            cond = {}
            for k, a in enumerate(tree.nodes[n0].actions):
                pinned = sigma.copy()
                for j in range(len(tree.nodes[n0].actions)):
                    if j != k:
                        pinned[n0, :, j] = 0.0      # keep the real frequency, drop the others
                kr2 = R.kind_reach(tree, pinned)
                p2 = R.terminal_reach(tree, pinned)
                cond[floor3.ACTION_NAMES[a]] = {
                    "P": round(float(p2.sum()), 6),
                    "kind_reach": {kk: round(vv / float(p2.sum()), 6) for kk, vv in kr2.items()},
                }
            ar["conditional_on_short_firstin"] = cond
        # every node of the short seat with an all-in option facing a raise
        for nd in tree.nodes:
            if nd.seat == 0 and nd.history and floor3.ALLIN in nd.actions:
                ar[f"short_node_{nd.index}"] = {"hist": [list(h) for h in nd.history],
                                                **range_at(tree, sigma, nd.index, "facing")}
        arms[arm] = ar
        print(f"[{arm}] {json.dumps({k: v for k, v in ar.items() if k != 'history'}, default=str)}",
              flush=True)
    rec["arms"] = arms
    rec["chart_diff"] = {a: compare(solved["asis"], solved[a])
                         for a in wanted if a != "asis"}
    print("chart_diff: " + json.dumps(rec["chart_diff"]), flush=True)
    Path(__file__).with_name(f"ab-{name}-{mode}.json").write_text(json.dumps(rec, indent=1))
    np.savez_compressed(Path(__file__).with_name(f"ab-{name}-{mode}.npz"),
                        **{f"{arm}_sigma": solved[arm]["sigma"] for arm in solved},
                        **{f"{arm}_nodes": np.array([nd.index for nd in solved[arm]["tree"].nodes])
                           for arm in solved})


if __name__ == "__main__":
    main()
