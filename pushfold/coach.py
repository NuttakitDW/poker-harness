"""The Coach: replays the table over and over, nudging each seat toward what paid more.

Full-width CFR over all 169 classes at once (no sampling: the tree is tiny).
Seats update one at a time. Methods:
  cfr   plain regret matching, uniform average
  cfr+  regrets floored at 0, average weighted by iteration (Tammelin 2014)
  dcfr  discounted: positive regrets x t^1.5/(t^1.5+1), negative x 0.5, average x (t/(t+1))^2
Stop rule: every `check_every` iterations the Auditor measures the average strategy;
stop once no seat can gain more than `target` bb per hand.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Callable

import numpy as np

from pushfold import auditor, floor, hands, pricer
from pushfold.spot import Spot

METHODS = ("cfr", "cfr+", "dcfr")
ALPHA, BETA, GAMMA = 1.5, 0.0, 2.0
WARM_REGRET = 0.1  # warm start: regrets = cached strategy x this, so iteration 1 plays it
DISPLAY_CUTOFF = 0.01


@dataclasses.dataclass(frozen=True)
class Result:
    spot: Spot
    tree: floor.Tree
    strategy: np.ndarray                 # (nodes, 169, 2) average strategy, raw
    iterations: int
    exploitability: float
    seconds: float
    history: tuple[tuple[int, float], ...]  # (iteration, exploitability) at every check
    warm: bool = False                      # started from a cached neighbour

    def node(self, seat: int, history: tuple[int, ...] | None = None) -> floor.Node:
        """The node of `seat`; default: everyone before it folded (the first-in spot)."""
        history = history if history is not None else (floor.FOLD,) * seat
        return next(n for n in self.tree.nodes if n.seat == seat and n.history == history)

    def chart(self, seat: int, history: tuple[int, ...] | None = None) -> np.ndarray:
        """13x13 grid of shove/call frequency, mixes under 1% rounded away (display only)."""
        p = self.strategy[self.node(seat, history).index][:, floor.JAM].copy()
        p[p < DISPLAY_CUTOFF] = 0.0
        p[p > 1 - DISPLAY_CUTOFF] = 1.0
        return p.reshape(13, 13)

    def range_pct(self, seat: int, history: tuple[int, ...] | None = None) -> float:
        """Share of all dealt hands that shove/call here, weighted by combos."""
        return float(hands.PRIOR @ self.strategy[self.node(seat, history).index][:, floor.JAM])


class Library:
    """Solved spots, so a new spot can start from its nearest solved neighbour.

    Neighbours must have the same table size and ante mode (same tree shape).
    Distance = sum of stack differences + ante difference, in bb.
    """

    def __init__(self) -> None:
        self._results: list[Result] = []

    def __len__(self) -> int:
        return len(self._results)

    def add(self, result: Result) -> None:
        self._results.append(result)

    def nearest(self, spot: Spot) -> Result | None:
        same = [r for r in self._results
                if r.spot.n == spot.n and r.spot.ante_mode == spot.ante_mode]
        if not same:
            return None
        return min(same, key=lambda r: sum(abs(a - b) for a, b in zip(r.spot.stacks, spot.stacks))
                   + abs(r.spot.ante - spot.ante))


def _match(regret: np.ndarray) -> np.ndarray:
    positive = np.maximum(regret, 0.0)
    total = positive.sum(axis=-1, keepdims=True)
    return np.where(total > 0, positive / np.where(total > 0, total, 1), 0.5)


def solve(spot: Spot, method: str = "cfr+", target: float = 0.01, check_every: int = 50,
          max_iters: int = 20_000, warm: np.ndarray | None = None,
          library: Library | None = None, log: Callable[[str], None] | None = None) -> Result:
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; pick one of {METHODS}")
    began = time.perf_counter()
    if warm is None and library is not None:
        neighbour = library.nearest(spot)
        warm = neighbour.strategy if neighbour is not None else None
    tree = floor.build(spot)
    plans = pricer.plan(tree)
    shape = (len(tree.nodes), len(hands.CLASSES), 2)
    regret = np.zeros(shape)
    total = np.zeros(shape)
    if warm is not None:
        # Seed only the regrets. Preloading the average too anchored it to the neighbour
        # and took 3-5x MORE iterations in tests; this way the average starts fresh.
        regret = warm * WARM_REGRET
    sigma = _match(regret) if warm is not None else np.full(shape, 0.5)
    history: list[tuple[int, float]] = []
    exploit = float("inf")
    t = 0
    while t < max_iters:
        t += 1
        for p in plans:
            if not len(p.nodes):
                continue
            cfv, _ = pricer.values(p, pricer.columns(sigma))
            mine = sigma[p.nodes]
            gain = cfv - (mine * cfv).sum(axis=2, keepdims=True)
            r = regret[p.nodes]
            if method == "cfr+":
                r = np.maximum(r + gain, 0.0)
            elif method == "dcfr":
                r = np.where(r > 0, r * t**ALPHA / (t**ALPHA + 1), r * t**BETA / (t**BETA + 1)) + gain
            else:
                r = r + gain
            regret[p.nodes] = r
            weight = {"cfr": 1.0, "cfr+": float(t)}.get(method)
            if weight is None:
                total[p.nodes] *= ((t - 1) / t) ** GAMMA
                weight = 1.0
            total[p.nodes] += weight * mine
            sigma[p.nodes] = _match(r)
        if t % check_every == 0:
            average = total / total.sum(axis=2, keepdims=True)
            exploit = auditor.audit(tree, average, plans).exploitability
            history.append((t, exploit))
            if log:
                log(f"iter {t:>6}  exploitability {exploit:.5f} bb")
            if exploit < target:
                break
    average = total / total.sum(axis=2, keepdims=True)
    result = Result(spot, tree, average, t, exploit, time.perf_counter() - began, tuple(history),
                    warm is not None)
    if library is not None:
        library.add(result)
    return result
