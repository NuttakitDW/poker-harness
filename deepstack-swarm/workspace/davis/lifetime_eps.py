"""Per-hand sigma of a solved push/fold strategy, and the lifetime-of-play epsilon.

Claim being tested (Cepheus's argument, Science 2015, as relayed by bowling): if a strategy
is played for a human lifetime of hands, the empirical mean of the per-hand result has
standard error sigma / sqrt(N) with N = 200 hands/hr x 12 hr/day x 365 day/yr x 70 yr
= 61,320,000. So an exploitability below

    eps = 1.64 * sigma / sqrt(61,320,000)

cannot be distinguished from exact by a lifetime of play (1.64 sd = 95% two-sided).

sigma is the standard deviation of ONE hand's outcome for one seat while every seat plays
the solved average strategy (self-play), on a real deal: n distinct hole-card pairs from one
52-card deck, sampled actions from sigma, five board cards if two or more seats are all in.
Chip EV is in bb/hand; ICM is in ICM chips/hand (pushfold/icm.py, prizes scaled to the chips
in play), measured as the ICM value of the final stack minus the ICM value of the starting
stack, exactly as pushfold/icm_pricer.py prices a terminal.

Nothing in pushfold/ is edited. Run from the repo root:

    PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/lifetime_eps.py
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np

from pushfold import auditor, cashier, coach, floor, hands, icm, oddsmaker
from pushfold.spot import Spot

FOLD, JAM = floor.FOLD, floor.JAM
LIFETIME = 200 * 12 * 365 * 70      # 61,320,000 hands
Z = 1.64
BLOCKS = 40                          # block bootstrap for the standard error of sigma
ICM_BATCH = 20_000

_CARD_CLASS = np.full((52, 52), -1, dtype=np.int16)
for _i, (_a, _b) in enumerate(hands.COMBOS):
    _CARD_CLASS[_a, _b] = hands.CLASS_OF[_i]
    _CARD_CLASS[_b, _a] = hands.CLASS_OF[_i]


# ------------------------------------------------------------------ simulator

def uniforms(n_hands: int, n: int, seed: int) -> np.ndarray:
    """Common random numbers for action sampling: the same draw for every strategy compared."""
    return np.random.default_rng(seed).random((n_hands, n))


def simulate(spot: Spot, tree: floor.Tree, sigmas: dict, n_hands: int, seed: int,
             payouts: icm.Payouts | None = None, u: np.ndarray | None = None) -> np.ndarray:
    """(n_hands, n) payoff per hand per seat. `sigmas`: seat -> (nodes, 169, 2) strategy.

    With `u` (seats x hands of uniform draws from `uniforms`) the walk makes no random draws
    of its own, so two strategies see the same deals and the same action draws: the per-hand
    difference is then a paired comparison, not two independent samples.
    """
    n = spot.n
    rng = np.random.default_rng(seed)
    nodes_at = {(nd.seat, nd.history): nd.index for nd in tree.nodes}
    forced = set(spot.forced)
    forced_after = [sum(1 for f in forced if f > seat) for seat in range(n)]
    term_of = {z.actions: z.index for z in tree.terminals}
    settle = [cashier.settle(spot, z.jammers) for z in tree.terminals]
    cap = floor.MAX_ALLIN

    net = np.zeros((n_hands, n))
    show = []                       # (row, terminal index, alive seats, their holes, board)
    for i in range(n_hands):
        deck = rng.permutation(52)
        hole = deck[:2 * n].reshape(n, 2)
        cls = _CARD_CLASS[hole[:, 0], hole[:, 1]]
        actions: list[int] = []
        history: tuple[int, ...] = ()
        jams = 0
        for seat in range(n):
            if seat in forced:
                actions.append(JAM)
                history += (JAM,)
                jams += 1
                continue
            ahead = jams + forced_after[seat]
            if (seat == n - 1 and ahead == 0) or ahead >= cap:
                actions.extend(JAM if s in forced else floor.IDLE for s in range(seat, n))
                break
            p = sigmas[seat][nodes_at[(seat, history)]][cls[seat]]
            a = JAM if rng.random() < p[JAM] else FOLD
            actions.append(a)
            history += (a,)
            if a == JAM:
                jams += 1
        t = term_of[tuple(actions)]
        z = tree.terminals[t]
        if len(z.jammers) >= 2:
            show.append((i, t, z.alive, hole[list(z.alive)].copy(), deck[2 * n:2 * n + 5].copy()))
        else:
            net[i] = settle[t].fixed

    groups: dict[tuple[int, ...], list[int]] = {}
    for k, item in enumerate(show):
        groups.setdefault(item[2], []).append(k)
    for alive, idx in groups.items():
        a = len(alive)
        H = np.stack([show[k][3] for k in idx])          # (m, a, 2)
        B = np.stack([show[k][4] for k in idx])          # (m, 5)
        s = np.stack([oddsmaker.strength(H[:, j, :], B) for j in range(a)], axis=1)
        place = 1 + (s[:, None, :] > s[:, :, None]).sum(axis=2)
        for j, k in enumerate(idx):
            ranks = {alive[q]: int(place[j, q]) for q in range(a)}
            net[show[k][0]] = settle[show[k][1]].net_for(ranks)

    if payouts is None:
        return net
    before = icm.value(np.array([spot.stacks]), spot.stacks, payouts)[0]
    out = np.empty_like(net)
    for lo in range(0, n_hands, ICM_BATCH):
        hi = min(lo + ICM_BATCH, n_hands)
        out[lo:hi] = icm.value(spot.stacks + net[lo:hi], spot.stacks, payouts) - before
    return out


# ------------------------------------------------------------------ statistics

def describe(net: np.ndarray) -> list[dict]:
    """Per-seat mean, sigma, block-bootstrap standard error of sigma, and the lifetime eps."""
    n_hands, n = net.shape
    per = []
    for seat in range(n):
        x = net[:, seat]
        blocks = np.array_split(x, BLOCKS)
        sigmas = np.array([b.std(ddof=1) for b in blocks])
        sigma = float(np.sqrt(np.mean(sigmas ** 2)))     # pooled, == x.std(ddof=0)-ish
        sigma = float(x.std(ddof=0))
        se_sigma = float(sigmas.std(ddof=1) / np.sqrt(BLOCKS))
        eps = Z * sigma / np.sqrt(LIFETIME)
        per.append(dict(seat=seat, mean=float(x.mean()), se_mean=float(sigma / np.sqrt(n_hands)),
                        sigma=sigma, se_sigma=se_sigma, eps=eps))
    return per


def solve_spot(spot: Spot, target: float, payouts, max_iters: int = 20_000, check_every: int = 25):
    began = time.perf_counter()
    r = coach.solve(spot, method="cfr+", target=target, check_every=check_every,
                    max_iters=max_iters, payouts=payouts)
    return r, time.perf_counter() - began


# ------------------------------------------------------------------ spots

def bubble(context: dict) -> icm.Payouts:
    """Chip-conserving Payouts for a stage: table stacks + the rest of the field as a crowd."""
    left, avg = context["players_left"], context["avg_bb"]
    table = context["table"]
    crowd = left - len(table)
    away = left * avg - sum(table)
    return icm.Payouts(prizes=context["prizes"][:min(len(context["prizes"]), left)],
                       crowd=crowd, crowd_stack=away / crowd if crowd else 0.0)


def prize_ladder(filename: str) -> tuple[str, tuple[float, ...], float]:
    import json as _json
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    with open(root / "deepstack-swarm" / "assets" / filename) as fh:
        s = _json.load(fh)["structures"][0]
    pz = s["prizes"]
    return s["name"], tuple(pz[str(k)] for k in sorted(int(k) for k in pz)), float(s["chips"])


def spots() -> list[dict]:
    _, p300, _ = prize_ladder("mtt_300_players.json")
    table6 = (10.0,) * 6
    bubble_ctx = dict(prizes=p300, players_left=46, avg_bb=20.0, table=table6)
    hu_prizes = (p300[0], p300[1])
    return [
        dict(name="HU-10bb", spot=Spot((10.0, 10.0)), payouts=None),
        dict(name="HU-10bb-icm-ft", spot=Spot((10.0, 10.0)),
             payouts=icm.Payouts(prizes=hu_prizes),
             note="ICM, heads-up of the 300-runner field: 1st/2nd only, no field"),
        dict(name="3h-10bb", spot=Spot((10.0,) * 3), payouts=None),
        dict(name="6h-10bb-ante0.25-each", spot=Spot(table6, ante=0.25, ante_mode="each"),
             payouts=None),
        dict(name="6h-10bb-ante0.5-bb", spot=Spot(table6, ante=0.5, ante_mode="bb"),
             payouts=None),
        dict(name="6h-10bb-ante1.0-bb", spot=Spot(table6, ante=1.0, ante_mode="bb"),
             payouts=None),
        dict(name="6h-10bb-ante1.0-bb-bubble46", spot=Spot(table6, ante=1.0, ante_mode="bb"),
             payouts=bubble(bubble_ctx),
             note="ICM, 46 left of 300, 45 paid, field average 20bb -> crowd 40 x 21.5bb"),
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--target", type=float, default=0.0005)
    ap.add_argument("--max-iters", type=int, default=20_000)
    ap.add_argument("--out", default="deepstack-swarm/workspace/davis/lifetime_eps.json")
    a = ap.parse_args()

    results = []
    for job in spots():
        spot, payouts = job["spot"], job["payouts"]
        r, secs = solve_spot(spot, a.target, payouts, a.max_iters)
        net = simulate(spot, r.tree, {s: r.strategy for s in range(spot.n)}, a.hands, a.seed,
                       payouts)
        unit = "ICM chips" if payouts else "bb"
        per = describe(net)
        ref = auditor.audit(r.tree, r.strategy, payouts=payouts)
        print(f"\n=== {job['name']}  ({unit}/hand)  n={spot.n} stacks={spot.stacks} "
              f"ante={spot.ante} {spot.ante_mode} fee={spot.fee}")
        if job.get("note"):
            print(f"    {job['note']}")
        print(f"    solve: cfr+ target={a.target} iters={r.iterations} "
              f"exploit={r.exploitability:.5f} {secs:.1f}s")
        print(f"    {'seat':>4} {'mean':>9} {'se(mean)':>9} {'sigma':>8} {'se(sigma)':>9} "
              f"{'eps':>9} {'audit EV':>9} {'mean-EV':>9}")
        for p, ev in zip(per, ref.ev):
            print(f"    {p['seat']:>4} {p['mean']:>9.5f} {p['se_mean']:>9.5f} "
                  f"{p['sigma']:>8.4f} {p['se_sigma']:>9.5f} {p['eps']:>9.6f} "
                  f"{ev:>9.5f} {p['mean'] - ev:>9.5f}")
        smax = max(p["sigma"] for p in per)
        smin = min(p["sigma"] for p in per)
        print(f"    sigma range {smin:.4f}-{smax:.4f}; eps at max sigma = "
              f"{Z * smax / np.sqrt(LIFETIME):.6f} {unit}/hand = "
              f"{1e3 * Z * smax / np.sqrt(LIFETIME):.4f} m{unit.split()[0]}/hand")
        results.append(dict(name=job["name"], note=job.get("note", ""), unit=unit,
                            stacks=list(spot.stacks), ante=spot.ante, ante_mode=spot.ante_mode,
                            fee=spot.fee, n=spot.n, target=a.target, iterations=r.iterations,
                            exploitability=r.exploitability, solve_seconds=secs,
                            hands=a.hands, seed=a.seed, per_seat=per,
                            audit_ev=[float(v) for v in ref.ev],
                            sigma_max=smax, sigma_min=smin,
                            eps_max=Z * smax / np.sqrt(LIFETIME),
                            eps_min=Z * smin / np.sqrt(LIFETIME)))

    with open(a.out, "w") as fh:
        json.dump(dict(lifetime_hands=LIFETIME, z=Z, target=a.target, hands=a.hands,
                       seed=a.seed, spots=results), fh, indent=1)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
