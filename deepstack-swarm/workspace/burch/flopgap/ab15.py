"""Tier 1 vs Tier 1.5: what the 3bet is used for and what it is worth.

Tier 1.5 (`floor3.build(..., tier15=True)`, `open3bet-design.md` Sec 15) is Tier 1 plus a 3bet
at `raises == 1` against a non-all-in aggressor, still no flat. At *equal* stacks both are
leaf-free, so the two charts are the same kind of object and can be compared directly.

Three measurements, all exact (`seqbr.audit`, no sampling):

  1. P(3bet) under the Tier 1.5 equilibrium, at every node where a 3bet is legal.
  2. The value of the 3bet action: zero a seat's 3bet probability in the Tier 1.5 equilibrium,
     renormalise its other actions, re-audit. That is a *lower bound* on the action's value,
     since the seat is not allowed to re-optimise its fold/all-in frequencies.
  3. The Tier 1 chart inside the Tier 1.5 game. Tier 1's action set is a subset of Tier 1.5's at
     every shared decision (FOLD/CALL/ALLIN only), so this embedding is exact -- the 3bet column
     is simply zero. Unreached Tier 1.5 nodes (raisers after a 3bet) are filled with the Tier 1.5
     equilibrium, which is the right counterfactual: the opponents keep the 3bet.

Usage: .venv/bin/python ab15.py [spot...]      spots: 3max 6max (default: both)
Writes ab15-<spot>.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for p in (ROOT, ROOT / "deepstack-swarm/workspace/burch/open3bet", ROOT / "deepstack-swarm/workspace/johanson", HERE):
    sys.path.insert(0, str(p))

from pushfold import hands, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import floor3  # noqa: E402
import solve3  # noqa: E402
import seqbr  # noqa: E402
import seqbr3  # noqa: E402

N = len(hands.CLASSES)
SPOTS = {"3max": (15.0,) * 3, "6max": (15.0,) * 6,
         "3max30": (30.0,) * 3, "6max30": (30.0,) * 6}


def solve_arm(stacks, kw, target, max_iters=20000):
    tree = floor3.build(Spot(stacks=stacks), **kw)
    sol = solve3.solve(tree, target, "cfr+", check_every=25, max_iters=max_iters)
    return tree, sol.st.average(), sol


def threebet_value(tree, sigma, seat_probe=None):
    """Zero the RAISE probability (only where raises == 1) and renormalise, per seat.

    Returns the max-seat EV loss in bb/hand. `seat_probe=None` zeroes every seat at once,
    otherwise only that seat. Loss is a lower bound on the value of the action.
    """
    g = seqbr3.from_floor3(tree)
    base = seqbr.audit(g, sigma, None)
    knock = sigma.copy()
    touched = 0
    for nd in tree.nodes:
        if nd.raises != 1 or floor3.RAISE not in nd.actions:
            continue
        if seat_probe is not None and nd.seat != seat_probe:
            continue
        k = nd.actions.index(floor3.RAISE)
        knocked = knock[nd.index, :, :len(nd.actions)].copy()
        knocked[:, k] = 0.0
        row = knocked.sum(axis=1, keepdims=True)
        row[row <= 0] = 1.0
        knock[nd.index, :, :len(nd.actions)] = knocked / row
        touched += 1
    alt = seqbr.audit(g, knock, None)
    return base.ev - alt.ev, touched


def embed_tier1_into_15(t1_tree, t1_sigma, t15_tree):
    """Tier 1's chart as a strategy on the Tier 1.5 tree, by (seat, history) -- action sets are
    nested, so each Tier 1 column maps to the same action's column in Tier 1.5."""
    key = {(nd.seat, nd.history): nd for nd in t1_tree.nodes}
    out = np.zeros((len(t15_tree.nodes), N, t15_tree.max_actions))
    filled = 0
    for nd in t15_tree.nodes:
        k = len(nd.actions)
        src = key.get((nd.seat, nd.history))
        if src is None:
            out[nd.index, :, :k] = np.ones((N, k)) / k      # unreached by a non-3betting seat
            continue
        filled += 1
        for j, a in enumerate(nd.actions):
            if a in src.actions:
                out[nd.index, :, j] = t1_sigma[src.index, :, src.actions.index(a)]
            else:
                out[nd.index, :, j] = 0.0                    # the 3bet, which Tier 1 lacks
        s = out[nd.index, :, :k].sum(axis=1, keepdims=True)
        s[s <= 0] = 1.0
        out[nd.index, :, :k] /= s
    return out, filled


def range_at(tree, sigma, nd, label=""):
    out = {}
    for j, a in enumerate(nd.actions):
        col = sigma[nd.index, :, j]
        out[floor3.ACTION_NAMES[a]] = round(float(col.mean()), 4)
        if a == floor3.RAISE:
            out["range_3bet"] = round(float(hands.PRIOR[col > 0.5].sum()), 4)
    return out


def main() -> None:
    names = sys.argv[1:] or ["3max", "6max"]
    for name in names:
        stacks = SPOTS[name]
        t15, s15, sol15 = solve_arm(stacks, dict(tier15=True), 0.001)
        t1, s1, sol1 = solve_arm(stacks, dict(tier1=True), 0.001)
        rec = {"spot": name, "stacks": list(stacks),
               "tier15": {"nodes": len(t15.nodes), "terminals": len(t15.terminals),
                          "counts": t15.counts(), "converged": sol15.converged,
                          "iters": sol15.history[-1][0], "gain": sol15.history[-1][1],
                          "seconds": round(sol15.seconds, 1)},
               "tier1": {"nodes": len(t1.nodes), "terminals": len(t1.terminals),
                         "counts": t1.counts(), "converged": sol1.converged,
                         "iters": sol1.history[-1][0], "gain": sol1.history[-1][1],
                         "seconds": round(sol1.seconds, 1)}}
        print(f"=== {name} {stacks} ===")
        for arm, r in (("tier15", rec["tier15"]), ("tier1", rec["tier1"])):
            print(f"  {arm:<7} nodes={r['nodes']:<4} terms={r['terminals']:<4} {r['counts']} "
                  f"conv={r['converged']} iters={r['iters']} gain={r['gain']:.6f}")

        # 1. how often the 3bet is used
        nodes3 = [nd for nd in t15.nodes if nd.raises == 1 and floor3.RAISE in nd.actions]
        per_seat = {}
        for nd in nodes3:
            col = s15[nd.index, :, nd.actions.index(floor3.RAISE)]
            per_seat.setdefault(nd.seat, []).append(float(col.mean()))
        rec["threebet_freq_by_seat"] = {s: round(float(np.mean(v)), 4) for s, v in sorted(per_seat.items())}
        rec["threebet_freq_overall"] = round(float(np.mean([v for vs in per_seat.values() for v in vs])), 4)
        print(f"  3bet nodes={len(nodes3)}  mean P(3bet) by seat={rec['threebet_freq_by_seat']}")

        # 2. what the 3bet is worth
        g15 = seqbr3.from_floor3(t15)
        base_ev = seqbr.audit(g15, s15, None).ev
        loss_all, touched = threebet_value(t15, s15, None)
        per_seat_loss = {}
        for s in range(len(stacks)):
            l, _ = threebet_value(t15, s15, s)
            per_seat_loss[s] = round(float(l[s]), 5)
        rec["threebet_value"] = {"nodes_touched": touched,
                                 "all_seats_max": round(float(loss_all.max()), 5),
                                 "per_seat": per_seat_loss}
        print(f"  zero the 3bet ({touched} nodes): EV loss max seat {loss_all.max():+.5f} bb/hand, "
              f"per seat {per_seat_loss}")

        # 3. the Tier 1 chart inside the Tier 1.5 game
        emb, filled = embed_tier1_into_15(t1, s1, t15)
        ev_t1_in_15 = seqbr.audit(g15, emb, None).ev
        cost = base_ev - ev_t1_in_15
        rec["tier1_in_tier15"] = {"matched_nodes": filled, "of": len(t15.nodes),
                                  "max_seat_cost": round(float(cost.max()), 5),
                                  "per_seat": [round(float(c), 5) for c in cost]}
        print(f"  Tier 1 chart inside the Tier 1.5 game ({filled}/{len(t15.nodes)} nodes matched): "
              f"max seat cost {cost.max():+.5f} bb/hand, per seat {np.round(cost, 5).tolist()}")
        Path(HERE / f"ab15-{name}.json").write_text(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
