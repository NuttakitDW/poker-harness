"""A heads-up open/3bet preflop tree where both seats act twice, and what it costs to audit
it with the push/fold shortcut.

Tree (SB = seat 0, BB = seat 1, equal stacks S, sb 0.5, bb 1, no ante):

    SB: fold | open 2.2 | all-in S
        open  -> BB: fold | call 2.2 | 3bet 6.6 | all-in S
                     3bet -> SB: fold | call 6.6 | all-in S
                                  all-in -> BB: fold | call
        all-in -> BB: fold | call

So SB acts at up to 2 nodes on one path and BB at up to 2 nodes on another. That is the only
structural difference from `pushfold/floor.py`, and it is enough to break
`pushfold/auditor.py`'s per-node maximum.

Leaf model for an ending that sees a flop: **L0 checkdown** (bowling's open3bet-design.md §3).
Nobody bets again; the pot is awarded at all-in equity among the players who reached the flop
and the rest of the stacks stay put. That is a distribution over final stacks, so it prices
under ICM. It is biased: it deletes position, fold equity and equity realization. Every number
here is a number about the model game including this leaf, not about no-limit hold'em.

Also here: a reference full-width CFR+ over the generic tree, used only to get strategies worth
auditing. `burch` owns the production solver.

Run: .venv/bin/python deepstack-swarm/workspace/johanson/toy_open3bet.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import seqbr  # noqa: E402
from pushfold import cashier, hands, icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

N = len(hands.CLASSES)
PRIOR = hands.PRIOR


# ---------------------------------------------------------------- settlement


def settle_bets(spot: Spot, paid: tuple[float, ...], alive: tuple[int, ...]) -> cashier.Settlement:
    """`cashier.settle` with the contributions given instead of derived from a jam/fold list.

    Identical layering rules; `cashier.settle(spot, jammers)` is the special case where every
    live seat is all-in. An open/3bet tree needs this generalisation (see the note to `burch`).
    """
    paid_v = np.array(paid, dtype=float)
    antes = np.array(spot.antes)
    fixed = -(paid_v + antes)
    pots: list[list] = []
    low = 0.0
    for high in sorted(set(paid_v[paid_v > 0].tolist())):
        parts = np.clip(paid_v - low, 0, high - low)
        eligible = tuple(s for s in alive if paid_v[s] >= high - 1e-12)
        if not eligible:
            fixed += parts
        elif len(eligible) == 1:
            fixed[eligible[0]] += parts.sum()
        elif pots and pots[-1][1] == eligible:
            pots[-1][0] += parts.sum()
        else:
            pots.append([parts.sum(), eligible])
        low = high
    dead = float(antes.sum())
    if len(alive) == 1:
        fixed[alive[0]] += dead
    elif dead and pots and pots[0][1] == tuple(alive):
        pots[0][0] += dead
    elif dead:
        pots.insert(0, [dead, tuple(alive)])
    if len(alive) > 1:
        fixed[list(alive)] -= spot.fee
    return cashier.Settlement(fixed, tuple(cashier.Layer(float(a), e) for a, e in pots))


# ---------------------------------------------------------------- the tree


def build(stack: float = 12.0, open_to: float = 2.2, threebet_mult: float = 3.0,
          spot: Spot | None = None) -> seqbr.Game:
    spot = spot or Spot(stacks=(stack, stack))
    S = spot.stacks[0]
    sb, bb = spot.blinds
    endings: list[seqbr.Ending] = []
    nodes: list[seqbr.Node] = []

    def end(paid: tuple[float, float], alive: tuple[int, ...], label: str) -> int:
        pot = float(sum(paid) + sum(spot.antes))
        endings.append(seqbr.Ending(len(endings), alive, settle_bets(spot, paid, alive), label, pot))
        return ~endings[-1].index

    three = min(threebet_mult * open_to, S)
    # Built deepest-first so a child index always exists before its parent names it.
    # 5: BB facing SB's 4bet all-in, after BB 3bet
    nodes.append(seqbr.Node(5, 1, (end((S, three), (0,), "o-3b-Ai-f"),
                                   end((S, S), (0, 1), "o-3b-Ai-c [all-in]")), ("fold", "call")))
    # 4: SB facing BB's all-in over the open
    nodes.append(seqbr.Node(4, 0, (end((open_to, S), (1,), "o-Ai-f"),
                                   end((S, S), (0, 1), "o-Ai-c [all-in]")), ("fold", "call")))
    # 3: SB facing BB's 3bet  (SB's SECOND decision)
    nodes.append(seqbr.Node(3, 0, (end((open_to, three), (1,), "o-3b-f"),
                                   end((three, three), (0, 1), "o-3b-c [FLOP]"),
                                   5), ("fold", "call", "all-in")))
    # 2: BB facing SB's all-in
    nodes.append(seqbr.Node(2, 1, (end((S, bb), (0,), "Ai-f"),
                                   end((S, S), (0, 1), "Ai-c [all-in]")), ("fold", "call")))
    # 1: BB facing the open
    nodes.append(seqbr.Node(1, 1, (end((open_to, bb), (0,), "o-f"),
                                   end((open_to, open_to), (0, 1), "o-c [FLOP]"),
                                   3, 4), ("fold", "call", "3bet", "all-in")))
    # 0: SB first in
    nodes.append(seqbr.Node(0, 0, (end((sb, bb), (1,), "f"), 1, 2),
                            ("fold", f"open {open_to}", "all-in")))
    return seqbr.Game(spot, tuple(sorted(nodes, key=lambda n: n.index)), tuple(endings), 0)


# ---------------------------------------------------------------- reference CFR+


def counterfactual(game: seqbr.Game, u: np.ndarray, sigma: np.ndarray, seat: int) -> dict:
    """cfv[node][h, a]: value of taking a at node then playing sigma, opponents' reach folded in,
    the seat's own reach to the node left out. The quantity CFR regret-matches on."""
    out: dict[int, np.ndarray] = {}

    def go(index: int) -> np.ndarray:
        if index < 0:
            return u[:, ~index]
        node = game.nodes[index]
        kids = np.stack([go(child) for child in node.children], axis=1)
        if node.seat != seat:
            return kids.sum(axis=1)
        out[node.index] = kids
        return (sigma[node.index, :, :kids.shape[1]] * kids).sum(axis=1)

    go(game.root)
    return out


def _match(regret: np.ndarray, legal: int) -> np.ndarray:
    positive = np.maximum(regret[:, :legal], 0.0)
    total = positive.sum(axis=1, keepdims=True)
    out = np.zeros_like(regret)
    out[:, :legal] = np.where(total > 0, positive / np.where(total > 0, total, 1), 1.0 / legal)
    return out


def solve(game: seqbr.Game, iters: int, payouts: icm.Payouts | None = None,
          check: int = 50, log=print) -> tuple[np.ndarray, list]:
    """Full-width CFR+ (Tammelin 2014) over the generic tree. Reference implementation."""
    width = game.width
    shape = (len(game.nodes), N, width)
    regret, total, weight_sum = np.zeros(shape), np.zeros(shape), 0.0
    sigma = game.uniform()
    legal = {n.index: len(n.children) for n in game.nodes}
    history = []
    for t in range(1, iters + 1):
        U = seqbr.values(game, sigma, payouts)
        for seat in range(game.spot.n):
            cfv = counterfactual(game, U[seat], sigma, seat)
            for index, kids in cfv.items():
                k = kids.shape[1]
                now = (sigma[index, :, :k] * kids).sum(axis=1, keepdims=True)
                regret[index, :, :k] = np.maximum(regret[index, :, :k] + kids - now, 0.0)
                total[index] += t * sigma[index]
                sigma[index] = _match(regret[index], legal[index])
        weight_sum += t
        if t % check == 0 or t == iters:
            average = _normalise(total, legal)
            report = seqbr.audit(game, average, payouts)
            history.append((t, report))
            if log:
                log(f"  iter {t:>5}  exact max gain {report.exploitability: .6f}  "
                    f"shortcut {report.shortcut.max(): .6f}  "
                    f"ratio {report.shortcut.max() / max(report.exploitability, 1e-12):6.2f}x")
    return _normalise(total, legal), history


def _normalise(total: np.ndarray, legal: dict) -> np.ndarray:
    out = np.zeros_like(total)
    for index, k in legal.items():
        s = total[index, :, :k].sum(axis=1, keepdims=True)
        out[index, :, :k] = np.where(s > 0, total[index, :, :k] / np.where(s > 0, s, 1), 1.0 / k)
    return out


# ---------------------------------------------------------------- the experiment


def anchors(game: seqbr.Game, rng) -> list:
    shape = (len(game.nodes), N, game.width)
    out = []
    for name, action in (("always-fold", 0), ("always-first-aggressive", 1)):
        s = np.zeros(shape)
        for node in game.nodes:
            s[node.index, :, min(action, len(node.children) - 1)] = 1.0
        out.append((name, s))
    out.append(("uniform", game.uniform()))
    for i in range(3):
        s = np.zeros(shape)
        for node in game.nodes:
            k = len(node.children)
            r = rng.random((N, k))
            s[node.index, :, :k] = r / r.sum(axis=1, keepdims=True)
        out.append((f"random-{i}", s))
    return out


def main() -> None:
    rng = np.random.default_rng(20260927)
    stack = 12.0
    game = build(stack)
    pot = seqbr.initial_pot(game.spot)
    print(f"toy open/3bet, heads-up, {stack}bb each, sb 0.5 bb 1, no ante, no fee, L0 flop leaf")
    print(f"nodes {len(game.nodes)}  endings {len(game.endings)}  initial pot {pot}bb")
    for node in game.nodes:
        print(f"  node {node.index} seat {node.seat} {node.labels}")
    print("  endings:", ", ".join(f"{e.index}:{e.label.strip()}" for e in game.endings))

    settings = [("chipEV", None),
                ("ICM 3-paid, 2 at other tables",
                 icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(12.0, 12.0)))]
    for mode, payouts in settings:
        unit = "ICM chips/hand" if payouts else "bb/hand"
        print(f"\n=== {mode} ({unit}) ===")
        print(f"{'strategy':<24} {'seat gains (exact)':<26} {'max':>9} {'shortcut':>9} "
              f"{'ratio':>7} {'%pot':>7}")
        for name, sigma in anchors(game, rng):
            r = seqbr.audit(game, sigma, payouts)
            print(f"{name:<24} {np.array2string(r.gain, precision=4, floatmode='fixed'):<26} "
                  f"{r.exploitability:9.5f} {r.shortcut.max():9.5f} "
                  f"{r.shortcut.max() / max(r.exploitability, 1e-12):6.2f}x "
                  f"{seqbr.as_pct_of_pot(r.exploitability, game.spot):6.2f}")
        print("  CFR+ from uniform:")
        average, history = solve(game, 400, payouts, check=50)
        t, last = history[-1]
        avg_pot = seqbr.average_pot(game, average)
        print(f"  after {t} iterations: exact per seat {np.array2string(last.gain, precision=5)} "
              f"{unit}; max {last.exploitability:.5f}; NashConv (sum) {last.nashconv:.5f}")
        print(f"    = {seqbr.as_pct_of_pot(last.exploitability, game.spot):.3f}% of the initial "
              f"{pot}bb pot, or {100 * last.exploitability / avg_pot:.3f}% of the average final "
              f"pot ({avg_pot:.2f}bb)")
        print(f"    shortcut would report {last.shortcut.max():.5f} "
              f"({last.shortcut.max() / max(last.exploitability, 1e-12):.2f}x the truth)")


if __name__ == "__main__":
    main()
