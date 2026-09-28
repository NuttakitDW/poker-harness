"""sigma_hand for the Tier 1 ICM grid spots (`bowling/tier1chart`), per cell.

`davis-lifetime-eps.md` derived eps = 1.64 sigma / sqrt(61,320,000) with sigma_hand = 3.0 ICM
chips/hand at ONE spot (6-handed 10bb, bb-ante 1.0, 46 left of 300) and `bowling` adopted that
single number (0.0006 ICM chips/hand) as the target for every cell of the 80-cell Tier 1 grid.
This file measures sigma_hand at the spots the grid actually solves, so the one number can be
checked per spot.

Same method as `lifetime_eps.py` sec 2, applied to the Tier 1 tree instead of `pushfold.floor`:
self-play, a real deal (n distinct hole-card pairs from one 52-card deck, common random numbers
for the action draws), the solved average strategy at every seat, five board cards when two or
more seats are all in, the payoff in ICM chips per `pushfold/icm.py` exactly as
`icm_pricer3`/`seqbr._worth` price a terminal.

The tree is `floor3.build(Spot((stack,)*n), tier1=True)` -- open-or-jam, no flat, no 3bet, no
FLOP terminal at equal stacks -- and the walk uses `seqbr3.from_floor3`'s child pointers, which
is the same adapter the auditor uses. Nothing outside `deepstack-swarm/workspace/` is edited.

    PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_sigma.py --list
    PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_sigma.py --spots small-bubble-n9-8
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT,
          ROOT / "deepstack-swarm" / "workspace" / "burch" / "open3bet",
          ROOT / "deepstack-swarm" / "workspace" / "bowling" / "tier1chart"):
    sys.path.insert(0, str(p))

from pushfold import hands, icm, oddsmaker       # noqa: E402
from pushfold.spot import Spot                    # noqa: E402

import floor3                                     # noqa: E402
import fasticm3                                   # noqa: E402
import icm_pricer3                                # noqa: E402
import pricer3                                    # noqa: E402
import seqbr3                                     # noqa: E402
import solve3                                     # noqa: E402
import scenarios as S                             # noqa: E402

LIFETIME = 200 * 12 * 365 * 70      # 61,320,000 hands
Z = 1.64
BLOCKS = 40
CELLS = ROOT / "deepstack-swarm" / "workspace" / "bowling" / "tier1chart" / "cells"

_CARD_CLASS = np.full((52, 52), -1, dtype=np.int16)
for _i, (_a, _b) in enumerate(hands.COMBOS):
    _CARD_CLASS[_a, _b] = hands.CLASS_OF[_i]
    _CARD_CLASS[_b, _a] = hands.CLASS_OF[_i]


# ------------------------------------------------------------------ the game

def game_and_payouts(setting: str, n: int, stack: float, left: int):
    tree = floor3.build(Spot(stacks=(stack,) * n), tier1=True)
    payouts = S.payouts(setting, n, left, stack)
    game = seqbr3.from_floor3(tree)
    return tree, game, payouts


def cell_key(setting: str, label: str, n: int, stack: float, left: int) -> str:
    return f"{setting}-{label}-n{n}-{stack:g}bb-left{left}"


def strategy_for(setting: str, label: str, n: int, stack: float, left: int,
                 target: float, max_iters: int, check_every: int):
    """The solved average strategy: the grid's own npz if it converged, else a fresh solve."""
    key = cell_key(setting, label, n, stack, left)
    npz, js = CELLS / f"{key}.npz", CELLS / f"{key}.json"
    if npz.exists() and js.exists():
        rec = json.loads(js.read_text())
        if rec.get("converged"):
            with np.load(npz) as z:
                return z["sigma"], dict(source="grid cell", iters=rec["iters"],
                                        seconds=rec["seconds"], gain=rec["final_gain"],
                                        target=rec["target"])
    tree, game, payouts = game_and_payouts(setting, n, stack, left)
    began = time.perf_counter()
    sol = solve3.solve_icm(tree, payouts, target, "cfr+", check_every=check_every,
                           max_iters=max_iters)
    return (sol.st.average(),
            dict(source="fresh solve", iters=sol.history[-1][0],
                 seconds=round(time.perf_counter() - began, 1),
                 gain=sol.history[-1][1], converged=sol.converged, target=target))


def audit_icm(tree, payouts, sigma) -> np.ndarray:
    """`fasticm3.FastAuditor` EV per seat, the same number the grid's stop rule reads."""
    plan = icm_pricer3.plan(tree, payouts)
    game = seqbr3.from_floor3(tree)
    aud = fasticm3.FastAuditor(game, fasticm3.plan(tree, payouts, plan), payouts)
    return aud.audit(sigma).ev


# ------------------------------------------------------------------ simulator

def simulate(game, sigma: np.ndarray, n_hands: int, seed: int) -> np.ndarray:
    """(n_hands, n) net chips per hand per seat, every seat playing `sigma`. No ICM yet."""
    spot = game.spot
    n = spot.n
    rng = np.random.default_rng(seed)
    net = np.zeros((n_hands, n))
    show: list[tuple[int, int, tuple[int, ...], np.ndarray, np.ndarray]] = []

    children = [np.asarray(nd.children) for nd in game.nodes]
    for i in range(n_hands):
        deck = rng.permutation(52)
        hole = deck[:2 * n].reshape(n, 2)
        cls = _CARD_CLASS[hole[:, 0], hole[:, 1]]
        idx = game.root
        while idx >= 0:
            seat = game.nodes[idx].seat
            p = sigma[idx, cls[seat], :len(children[idx])]
            r = rng.random()
            a, acc = 0, p[0]
            while acc < r and a + 1 < len(p):
                a += 1
                acc += p[a]
            idx = int(children[idx][a])
        z = game.endings[~idx]
        if len(z.alive) >= 2:
            show.append((i, ~idx, z.alive, hole[list(z.alive)].copy(),
                         deck[2 * n:2 * n + 5].copy()))
        else:
            net[i] = z.settle.fixed

    groups: dict[tuple[int, ...], list[int]] = {}
    for k, item in enumerate(show):
        groups.setdefault(item[2], []).append(k)
    for alive, idxs in groups.items():
        a = len(alive)
        H = np.stack([show[k][3] for k in idxs])          # (m, a, 2)
        B = np.stack([show[k][4] for k in idxs])          # (m, 5)
        s = np.stack([oddsmaker.strength(H[:, j, :], B) for j in range(a)], axis=1)
        place = 1 + (s[:, None, :] > s[:, :, None]).sum(axis=2)
        for j, k in enumerate(idxs):
            ranks = {alive[q]: int(place[j, q]) for q in range(a)}
            net[show[k][0]] = game.endings[show[k][1]].settle.net_for(ranks)
    return net


def to_icm(net: np.ndarray, stacks: tuple[float, ...], payouts: icm.Payouts) -> np.ndarray:
    """Per-hand ICM chips: ICM(final stack) - ICM(starting stack), as `seqbr._worth` prices it.

    One `icm.value` call per *distinct* outcome vector, not per hand: the net vector only takes
    finitely many values (one per ending x finishing order), and for the 1500-runner structure
    `crowd_harville` on 200,000 rows x 229 stacks would not fit in memory anyway.
    """
    uniq, inv = np.unique(np.round(net, 9), axis=0, return_inverse=True)
    before = icm.value(np.array([stacks]), stacks, payouts)[0]
    got = icm.value(uniq + np.array(stacks), stacks, payouts) - before
    return got[inv]


def describe(net: np.ndarray) -> list[dict]:
    n_hands, n = net.shape
    out = []
    for seat in range(n):
        x = net[:, seat]
        blocks = np.array_split(x, BLOCKS)
        sig = np.array([b.std(ddof=1) for b in blocks])
        sigma = float(x.std(ddof=0))
        se = float(sig.std(ddof=1) / np.sqrt(BLOCKS))
        out.append(dict(seat=seat, mean=float(x.mean()), se_mean=float(sigma / np.sqrt(n_hands)),
                        sigma=sigma, se_sigma=se, eps=Z * sigma / np.sqrt(LIFETIME)))
    return out


# ------------------------------------------------------------------ jobs

JOBS = [
    # (setting, stage label, n, stack)
    ("small", "bubble", 9, 8.0),
    ("big", "bubble", 6, 8.0),
    ("big", "bubble", 9, 8.0),
    ("big", "bubble", 6, 30.0),
    ("big", "bubble", 9, 30.0),
]

# Every cell of the 80-cell grid that a *cheap* solve can cover, for the spread question:
# both settings, both stages, n = 2/3/6, stacks 8 and 30bb. Cells already in `cells/` are
# simulated straight from the grid's own chart; the rest are solved here at `--target`.
def sweep() -> list[tuple[str, str, int, float]]:
    out = []
    for setting in ("small", "big"):
        for label, _left in S.stages(setting)[:2]:
            for n in (2, 3, 6):
                for stack in (8.0, 30.0):
                    out.append((setting, label, n, stack))
    return out


def existing() -> list[tuple[str, str, int, float]]:
    """Every grid cell already solved in `cells/`, as (setting, stage, n, stack)."""
    out = []
    for js in sorted(CELLS.glob("*.json")):
        rec = json.loads(js.read_text())
        if not rec.get("converged"):
            continue
        out.append((rec["setting"], rec["stage"], rec["n"], float(rec["stack"])))
    return sorted(set(out), key=lambda j: (j[0], j[1], j[2], j[3]))


def spot_of(job) -> tuple[str, str, int, float, int]:
    setting, label, n, stack = job
    left = dict(S.stages(setting))[label]
    return setting, label, n, stack, left


def run(job, hands: int, seed: int, target: float, max_iters: int, check_every: int,
        icm_hands: bool = True) -> dict:
    setting, label, n, stack, left = spot_of(job)
    key = cell_key(setting, label, n, stack, left)
    tree, game, payouts = game_and_payouts(setting, n, stack, left)
    sigma, how = strategy_for(setting, label, n, stack, left, target, max_iters, check_every)
    print(f"{key:<30} [{how['source']}] {how['iters']} it, gain {how['gain']:.6f}, "
          f"{how['seconds']}s; nodes {len(tree.nodes)}, crowd {payouts.crowd}", flush=True)

    t0 = time.perf_counter()
    raw = simulate(game, sigma, hands, seed)
    sim_s = time.perf_counter() - t0
    net = to_icm(raw, tree.spot.stacks, payouts)
    per = describe(net)
    ev = audit_icm(tree, payouts, sigma)

    print(f"    {'seat':>4} {'mean':>10} {'se(mean)':>9} {'sigma':>8} {'se(sig)':>8} "
          f"{'eps':>9} {'audit EV':>10} {'mean-EV':>9}")
    for p, e in zip(per, ev):
        print(f"    {p['seat']:>4} {p['mean']:>10.5f} {p['se_mean']:>9.5f} {p['sigma']:>8.4f} "
              f"{p['se_sigma']:>8.4f} {p['eps']:>9.6f} {e:>10.5f} {p['mean'] - e:>9.5f}")
    smax = max(p["sigma"] for p in per)
    smin = min(p["sigma"] for p in per)
    print(f"    sigma {smin:.4f}-{smax:.4f} ICM chips; eps at max sigma {1e3 * Z * smax / np.sqrt(LIFETIME):.4f} "
          f"mICM/hand, at min sigma {1e3 * Z * smin / np.sqrt(LIFETIME):.4f}; sim {sim_s:.1f}s",
          flush=True)

    return dict(cell=key, setting=setting, stage=label, n=n, stack=stack, left=left,
                crowd=payouts.crowd, prizes_paid=len(payouts.prizes), nodes=len(tree.nodes),
                strategy=how, hands=hands, seed=seed, sim_seconds=round(sim_s, 1),
                per_seat=per, audit_ev=[float(v) for v in ev],
                sigma_max=smax, sigma_min=smin,
                eps_max=Z * smax / np.sqrt(LIFETIME), eps_min=Z * smin / np.sqrt(LIFETIME))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--target", type=float, default=0.0006)
    ap.add_argument("--max-iters", type=int, default=20_000)
    ap.add_argument("--check-every", type=int, default=25)
    ap.add_argument("--spots", default=None,
                    help="comma-separated cell keys (or prefixes), 'sweep', 'existing', 'list'")
    ap.add_argument("--out", default=str(ROOT / "deepstack-swarm" / "workspace" / "davis" / "grid_sigma.json"))
    a = ap.parse_args()

    if a.spots == "list":
        for j in JOBS:
            print(cell_key(*spot_of(j)))
        return
    if a.spots == "sweep":
        jobs = sweep()
    elif a.spots == "existing":
        jobs = existing()
    elif a.spots:
        want = [s.strip() for s in a.spots.split(",") if s.strip()]
        pool = JOBS + sweep() + existing()
        jobs = [j for j in pool if any(cell_key(*spot_of(j)).startswith(w) for w in want)]
        if not jobs:
            raise SystemExit(f"no job matches {want}")
    else:
        jobs = JOBS

    results = []
    for j in jobs:
        try:
            results.append(run(j, a.hands, a.seed, a.target, a.max_iters, a.check_every))
        except Exception as e:  # noqa: BLE001
            print(f"  {cell_key(*spot_of(j))}: {type(e).__name__}: {e}", flush=True)
            results.append(dict(cell=cell_key(*spot_of(j)), error=f"{type(e).__name__}: {e}"))
        with open(a.out, "w") as fh:
            json.dump(dict(lifetime_hands=LIFETIME, z=Z, hands=a.hands, seed=a.seed,
                           target=a.target, cells=results), fh, indent=1)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
