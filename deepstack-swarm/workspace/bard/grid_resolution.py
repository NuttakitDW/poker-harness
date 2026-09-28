"""How fine must an ICM chart grid be? Measured in the push/fold proxy game.

Proxy: pushfold/ (all-in or fold, 169 classes), ICM payouts from the two asset files.
The open/3bet game of ICM-OPEN3BET-v0 does not exist yet, so every number here is about
the push/fold game and is a *lower bound on the axes that matter*, not the final grid.

Distance between two charts at one node, in "share of dealt hands played differently":
    d = sum_h PRIOR[h] * |p1[h] - p2[h]|          (combo-weighted total variation)
Reported per node and as the max over nodes. A product tolerance of 2% of hands is used
as the illustrative threshold; it is a choice, not a result.
"""
from __future__ import annotations
import argparse, importlib.util, itertools, json, time
import numpy as np
from pushfold import coach, floor, hands, icm
from pushfold.spot import Spot

spec = importlib.util.spec_from_file_location("g", "deepstack-swarm/workspace/bard/icm_geometry.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

TARGET, CHECK, MAXIT = 0.003, 25, 600


def solve(stacks, P, method="cfr+", lib=None):
    return coach.solve(Spot(stacks=tuple(float(s) for s in stacks)), method=method,
                       target=TARGET, check_every=CHECK, max_iters=MAXIT, payouts=P, library=lib)


def dist(a: coach.Result, b: coach.Result):
    """Per-node combo-weighted TV distance. Trees must have the same shape."""
    assert a.strategy.shape == b.strategy.shape, "tree shapes differ; not comparable"
    pa = a.strategy[:, :, floor.JAM]
    pb = b.strategy[:, :, floor.JAM]
    per = (hands.PRIOR[None, :] * np.abs(pa - pb)).sum(axis=1)
    return per, float(per.max())


def label_nodes(r: coach.Result):
    names = r.spot.names
    out = []
    for nd in r.tree.nodes:
        h = "".join("f" if x == floor.FOLD else "J" for x in nd.history)
        out.append(f"{names[nd.seat]}|{h or '-'}")
    return out


def noise_floor(prizes, left, A, n, stack):
    st = (stack,) * n
    P, _ = g.payouts_for(prizes, left, st, A)
    rs = {m: solve(st, P, method=m) for m in ("cfr+", "dcfr")}
    per, mx = dist(rs["cfr+"], rs["dcfr"])
    return mx, rs["cfr+"].exploitability, rs["dcfr"].exploitability


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=["noise", "stage", "cross", "hero", "config"])
    ap.add_argument("--n", type=int, default=6)
    a = ap.parse_args()
    files = {"small": "mtt_300_players.json", "big": "mtt_1500_payout.json"}
    P300 = g.load(files["small"])
    P1500 = g.load(files["big"])

    if a.part == "noise":
        print("# noise floor: cfr+ vs dcfr, same spot. max node TV distance (share of hands).")
        for n in (2, 6, 9):
            for left, A in ((46, 20), (18, 20), (9, 20)):
                if left < n:
                    continue
                mx, e1, e2 = noise_floor(P300[1], left, A, n, 15.0)
                print(f"  {n}-max {left:>3} left A={A}: max TV {mx*100:5.2f}%  "
                      f"exploit cfr+ {e1:.4f} dcfr {e2:.4f} ICM chips/hand")

    if a.part == "stage":
        n = a.n
        print(f"# stage axis, {n}-max equal 15bb, small tournament (300 runners, 45 paid).")
        print("# adjacent-stage chart distance vs bubble-factor gap.")
        stages = [s for s in g.STAGES_LIST_300 if s[1] >= n]
        rows = []
        for label, left in stages:
            for A in (12.0, 20.0, 30.0, 45.0):
                st = (15.0,) * n
                try:
                    P, cs = g.payouts_for(P300[1], left, st, A)
                except Exception:
                    continue
                bf = g.bfs(st, P)[0]
                r = solve(st, P)
                rows.append((label, left, A, cs, bf, r))
                print(f"  {label:<15} A={A:>4.0f} crowd={cs:>6.1f}  BF={bf:.3f}  "
                      f"exploit={r.exploitability:.4f}  SBfirstin={r.range_pct(n-2)*100:5.1f}%  "
                      f"UTGfirstin={r.range_pct(0)*100:5.1f}%  iters={r.iterations}")
        print("\n# pairwise: BF gap -> max node chart distance")
        for (l1, lf1, A1, _, b1, r1), (l2, lf2, A2, _, b2, r2) in itertools.combinations(rows, 2):
            _, mx = dist(r1, r2)
            print(f"  dBF={abs(b1-b2):.3f}  dTV={mx*100:5.2f}%   [{l1} A{A1:.0f}] vs [{l2} A{A2:.0f}]")

    if a.part == "cross":
        n = a.n
        print(f"# cross-payout: same stage fraction, small vs big tournament, {n}-max equal 15bb")
        pairs = [("late reg", 250, 1200), ("pre-bubble x1.3", 60, 300), ("bubble", 46, 226),
                 ("just ITM", 44, 224), ("ITM half-paid", 27, 112), ("ITM 18", 18, 18),
                 ("FT bubble", 10, 10), ("FT", 9, 9)]
        for label, l300, l1500 in pairs:
            for A in (12.0, 20.0, 30.0):
                st = (15.0,) * n
                try:
                    Pa, _ = g.payouts_for(P300[1], l300, st, A)
                    Pb, _ = g.payouts_for(P1500[1], l1500, st, A)
                except Exception:
                    continue
                ba, bb_ = g.bfs(st, Pa)[0], g.bfs(st, Pb)[0]
                ra, rb = solve(st, Pa), solve(st, Pb)
                _, mx = dist(ra, rb)
                print(f"  {label:<16} A={A:>4.0f}  BF {ba:.3f} vs {bb_:.3f}  dTV={mx*100:5.2f}%  "
                      f"SB first-in {ra.range_pct(n-2)*100:5.1f}% vs {rb.range_pct(n-2)*100:5.1f}%")

    if a.part == "hero":
        n = a.n
        print(f"# hero-stack axis, {n}-max, everyone equal at s bb, bubble stage (46 left, A=20)")
        prev = None
        for s in (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 20, 25, 30):
            st = (float(s),) * n
            P, _ = g.payouts_for(P300[1], 46, st, 20.0)
            r = solve(st, P)
            line = (f"  {s:>3}bb  BF={g.bfs(st,P)[0]:.3f}  exploit={r.exploitability:.4f}  "
                    f"SB first-in={r.range_pct(n-2)*100:5.1f}%")
            if prev is not None and prev[1].strategy.shape == r.strategy.shape:
                _, mx = dist(prev[1], r)
                line += f"   dTV vs {prev[0]}bb = {mx*100:5.2f}%"
            print(line)
            prev = (s, r)

    if a.part == "config":
        n = a.n
        print(f"# table-configuration axis, {n}-max, bubble stage (46 left, A=20), hero 10bb in each")
        base = None
        cfgs = {
            "all 10bb": (10.0,) * n,
            "hero 10, rest 25": (10.0,) + (25.0,) * (n - 1),
            "hero 10, rest 40": (10.0,) + (40.0,) * (n - 1),
            "hero 10, one 60 rest 15": (10.0,) + (15.0,) * (n - 2) + (60.0,),
            "hero 10, blinds short 6": (10.0,) * (n - 2) + (6.0, 6.0),
            "hero 10, blinds deep 30": (10.0,) * (n - 2) + (30.0, 30.0),
        }
        for label, st in cfgs.items():
            P, cs = g.payouts_for(P300[1], 46, st, 20.0)
            r = solve(st, P)
            bfv = " ".join(f"{b:.2f}" for b in g.bfs(st, P))
            line = (f"  {label:<24} exploit={r.exploitability:.4f} "
                    f"UTG first-in={r.range_pct(0)*100:5.1f}%  BFs={bfv}")
            if base is None:
                base = r
            elif base.strategy.shape == r.strategy.shape:
                _, mx = dist(base, r)
                line += f"  dTV vs all-10bb={mx*100:5.2f}%"
            print(line)


if __name__ == "__main__":
    main()
