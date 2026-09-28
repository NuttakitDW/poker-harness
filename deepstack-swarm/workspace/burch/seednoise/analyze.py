"""Chart movement and evaluation noise across seeds, from noise.npz.

dTV(node) = sum_h PRIOR[h] * |p1[node, h] - p2[node, h]|      (bard's combo-weighted dTV)
picked out as: max over nodes, and max over nodes reachable under the average strategy.
The scalar reach of a node is the product over the decisions on its path of the PRIOR-weighted
probability that the average player took the action taken -- an importance weight, not a
per-class probability (a per-class reach is not well defined for a class-indexed profile).

    .venv/bin/python deepstack-swarm/workspace/burch/seednoise/analyze.py
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "open3bet"))

from tableswap import seed_paths  # noqa: E402

from pushfold import hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import floor3  # noqa: E402

PRIOR = hands.PRIOR


def reach_of(tree: floor3.Tree, sigma: np.ndarray) -> np.ndarray:
    by_key = {(nd.seat, nd.history): nd for nd in tree.nodes}
    out = np.zeros(len(tree.nodes))
    for nd in tree.nodes:
        if not nd.history:
            out[nd.index] = 1.0
            continue
        pseat, paction = nd.history[-1]
        parent = by_key[(pseat, nd.history[:-1])]
        k = parent.actions.index(paction)
        p = float((PRIOR * sigma[parent.index, :, k]).sum())
        out[nd.index] = out[parent.index] * p
    return out


def dtv(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per node: sum_h PRIOR[h] |a[h] - b[h]|. a, b: (nodes, 169, A)."""
    return (PRIOR[None, :, None] * np.abs(a - b)).sum(axis=1)   # (nodes, A)


def main() -> None:
    d = np.load(HERE / "noise.npz", allow_pickle=False)
    meta = json.loads(str(d["meta"]))
    seeds = meta["seeds"]
    print("seeds:", seeds, "iters:", meta["iters"], "check:", meta["check"])

    spot = Spot(stacks=(15.0,) * 6)
    tree = floor3.build(spot, tier1=True)
    seat_of = np.array([nd.seat for nd in tree.nodes])
    nact = np.array([len(nd.actions) for nd in tree.nodes])

    strat = {m: {s: np.load(HERE / f"solve-{s}.npz")[f"{m}_{s}"]
                 for s in seeds} for m in ("chip", "icm")}
    rep: dict = {"cross": meta["cross"], "hist": meta["hist"],
                 "control": json.loads((HERE / "control.json").read_text()), "charts": {}}
    for mode in ("chip", "icm"):
        # Illegal action columns are held at zero by coach3 for every seed, so they contribute
        # nothing to the dTV; no masking needed.
        arrs = strat[mode]
        out = {}
        for x, y in itertools.combinations(seeds, 2):
            dd = dtv(arrs[x], arrs[y]).max(axis=1)          # (nodes,), max over actions
            r = reach_of(tree, arrs[y])
            cell = np.abs(arrs[x] - arrs[y]).max(axis=(1, 2))
            out[f"{x}{y}"] = {
                "dtv_max_all_nodes": float(dd.max()),
                "dtv_argmax_node": int(dd.argmax()),
                "dtv_argmax_seat": int(seat_of[dd.argmax()]),
                "dtv_max_cell": float(cell.max()),
                "dtv_max_cell_node": int(cell.argmax()),
                "dtv_max_reach_gt_1e-3": float(dd[r > 1e-3].max()),
                "dtv_max_reach_gt_1e-4": float(dd[r > 1e-4].max()),
                "dtv_reach_weighted_mean": float((dd * r).sum() / r.sum()),
                "dtv_mean_all_nodes": float(dd.mean()),
                "nodes_reach_gt_1e-3": int((r > 1e-3).sum()),
                "max_reach": float(r.max()),
            }
        rep["charts"][mode] = out
        # value-level: does the *evaluation* move with the seed, per cross-audit
        cv = {k: v for k, v in meta["cross"].items() if k.startswith(mode + "|")}
        rep.setdefault("cross_tables", {})[mode] = cv

    # -------------------------------------------------- evaluation noise floor
    print("\n=== cross-audit: strategy solved under X, audited under Y ===")
    for mode in ("chip", "icm"):
        unit = "bb/hand" if mode == "chip" else "ICM chips/hand"
        cv = rep["cross_tables"][mode]
        print(f"\n{mode} ({unit})")
        hdr = "        " + "".join(f"{y:>12}" for y in seeds)
        print(hdr)
        for x in seeds:
            print(f"  {x:<6}" + "".join(f"{cv[f'{mode}|{x}|{y}']:12.6f}" for y in seeds))
        same = [cv[f"{mode}|{x}|{x}"] for x in seeds]
        diff = [abs(cv[f"{mode}|{x}|{y}"]) for x in seeds for y in seeds]
        off = [abs(cv[f"{mode}|{x}|{y}"] - cv[f"{mode}|{y}|{y}"]) for x in seeds for y in seeds]
        print(f"  same-seed audits: {['%.6f' % v for v in same]}   spread {max(same)-min(same):.6f}")
        print(f"  max |cross - same-seed| = {max(off):.6f} {unit}")
        rep.setdefault("floor", {})[mode] = {
            "same_seed_spread": max(same) - min(same),
            "max_cross_minus_own_audit": max(off),
            "same_seed": dict(zip(seeds, same)),
        }

    # -------------------------------------------------- convergence trajectory
    print("\n=== exploitability trajectory (CFR+, 2000 iters, check_every=200) ===")
    for mode in ("chip", "icm"):
        unit = "bb/hand" if mode == "chip" else "ICM chips/hand"
        print(f"\n{mode} ({unit})   iters: " + " ".join(f"{it:>9}" for it, _ in meta["hist"][seeds[0]][mode]))
        for s in seeds:
            h = meta["hist"][s][mode]
            print(f"  {s:<6}" + " ".join(f"{v:9.6f}" for _, v in h))
        finals = [meta["hist"][s][mode][-1][1] for s in seeds]
        print(f"  final spread {max(finals)-min(finals):.6f} {unit} "
              f"(max/min = {max(finals):.6f}/{min(finals):.6f})")
        rep.setdefault("final", {})[mode] = {"values": dict(zip(seeds, finals)),
                                             "spread": max(finals) - min(finals)}

    print("\n=== chart movement (dTV) ===")
    print(json.dumps(rep["charts"], indent=1))
    (HERE / "analysis.json").write_text(json.dumps(rep, indent=1))
    print("\nwrote", HERE / "analysis.json")


if __name__ == "__main__":
    main()
