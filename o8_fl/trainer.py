"""External-sampling MCCFR with regret matching+ over the abstract heads-up FL O8 game.

Each iteration deals two hands and a board, computes both players' bucket on every street and the
showdown values once, then walks the betting tree for one traverser: every action of the traverser is
explored, the opponent's action is sampled from its current strategy, and the opponent's strategy is
added to the average with linear (iteration-number) weight. Threads share the tables without locks
(hogwild); one thread is fully deterministic for a given seed.

Information set = (public betting node, own bucket on the current street). Tables are flat: the row
of decision node d and bucket b starts at offsets[d] + 3 * b, with slots fold, check/call, bet/raise.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
from numba import njit, prange

from .buckets import Abstraction
from .pool import DealPool
from .evaluator import omaha_high, omaha_low
from .features import early_key, river_key
from .showdown import showdown_net
from .tree import DECISION, FOLD, PublicTree

SLOTS = 3
COMB = np.array([[math.comb(n, k) for k in range(5)] for n in range(53)], dtype=np.int64)


def layout(tree: PublicTree, bucket_counts: tuple[int, ...]) -> tuple[np.ndarray, int]:
    offsets = np.full(tree.node_count, -1, dtype=np.int64)
    size = 0
    for node in np.flatnonzero(tree.kind == DECISION):
        offsets[node] = size
        size += bucket_counts[tree.street[node]] * SLOTS
    return offsets, size


@njit(cache=True)
def combo_index_native(cards: np.ndarray) -> int:
    """Lexicographic rank of four distinct cards in combinations(range(52), 4) order."""
    c = np.sort(cards)
    rank = 0
    previous = -1
    for position in range(4):
        for skipped in range(previous + 1, c[position]):
            rank += COMB[51 - skipped, 3 - position]
        previous = c[position]
    return rank


@njit(cache=True)
def terminal_value(kind: np.ndarray, committed: np.ndarray, folder: np.ndarray, node: int, player: int,
                   high0: int, high1: int, low0: int, low1: int) -> float:
    if kind[node] == FOLD:
        loser = folder[node]
        return -committed[node, player] if loser == player else committed[node, 1 - player]
    net0 = showdown_net(committed[node, 0], high0, high1, low0, low1)
    return net0 if player == 0 else -net0


@njit(cache=True)
def traverser_for(start: int, i: int, thread: int, threads: int) -> int:
    """Seat to traverse on a thread's i-th iteration: alternates within every thread for any thread count."""
    return (start // threads + i + thread) % 2


@njit(cache=True)
def _deal(deck: np.ndarray, preflop: np.ndarray, flop_map: np.ndarray, turn_map: np.ndarray,
          buckets: np.ndarray, values: np.ndarray) -> None:
    np.random.shuffle(deck)
    board = deck[8:13]
    for p in range(2):
        hole = deck[4 * p:4 * p + 4]
        buckets[p, 0] = preflop[combo_index_native(hole)]
        buckets[p, 1] = flop_map[early_key(hole, board, 3)]
        buckets[p, 2] = turn_map[early_key(hole, board, 4)]
        values[p] = omaha_high(hole, board)
        buckets[p, 3] = river_key(hole, board, values[p])
        values[2 + p] = omaha_low(hole, board)


@njit(cache=True)
def _policy(regret: np.ndarray, base: int, children: np.ndarray, node: int, out: np.ndarray) -> None:
    total = 0.0
    legal = 0
    for s in range(SLOTS):
        out[s] = 0.0
        if children[node, s] >= 0:
            legal += 1
            if regret[base + s] > 0.0:
                out[s] = regret[base + s]
                total += out[s]
    for s in range(SLOTS):
        if children[node, s] >= 0:
            out[s] = out[s] / total if total > 0.0 else 1.0 / legal


# Not cached: numba's on-disk cache of a recursive function crashes when a later process loads it.
@njit
def _walk(node: int, traverser: int, kind: np.ndarray, actor: np.ndarray, street: np.ndarray,
          children: np.ndarray, committed: np.ndarray, folder: np.ndarray, offsets: np.ndarray,
          buckets: np.ndarray, values: np.ndarray, regret: np.ndarray, strategy_sum: np.ndarray,
          weight: float) -> float:
    if kind[node] != DECISION:
        return terminal_value(kind, committed, folder, node, traverser, values[0], values[1], values[2],
                              values[3])
    player = actor[node]
    base = offsets[node] + SLOTS * buckets[player, street[node]]
    sigma = np.empty(SLOTS)
    _policy(regret, base, children, node, sigma)
    if player == traverser:
        utility = np.zeros(SLOTS)
        value = 0.0
        for s in range(SLOTS):
            child = children[node, s]
            if child >= 0:
                utility[s] = _walk(child, traverser, kind, actor, street, children, committed, folder,
                                   offsets, buckets, values, regret, strategy_sum, weight)
                value += sigma[s] * utility[s]
        for s in range(SLOTS):
            if children[node, s] >= 0:
                updated = regret[base + s] + utility[s] - value
                regret[base + s] = updated if updated > 0.0 else 0.0
        return value
    for s in range(SLOTS):
        strategy_sum[base + s] += weight * sigma[s]
    pick = np.random.random()
    chosen = -1
    for s in range(SLOTS):
        if children[node, s] >= 0:
            chosen = s
            pick -= sigma[s]
            if pick < 0.0:
                break
    return _walk(children[node, chosen], traverser, kind, actor, street, children, committed, folder,
                 offsets, buckets, values, regret, strategy_sum, weight)


@njit(cache=True)
def _deal_from_pool(index: int, pool_cards: np.ndarray, pool_buckets: np.ndarray, preflop: np.ndarray,
                    deck: np.ndarray, buckets: np.ndarray, values: np.ndarray) -> None:
    for i in range(13):
        deck[i] = pool_cards[index, i]
    board = deck[8:13]
    for p in range(2):
        hole = deck[4 * p:4 * p + 4]
        buckets[p, 0] = preflop[combo_index_native(hole)]
        for s in range(3):
            buckets[p, s + 1] = pool_buckets[index, p, s]
        values[p] = omaha_high(hole, board)
        values[2 + p] = omaha_low(hole, board)


@njit(parallel=True)
def _run_pool(iterations: int, start: int, seed: int, threads: int, kind: np.ndarray, actor: np.ndarray,
              street: np.ndarray, children: np.ndarray, committed: np.ndarray, folder: np.ndarray,
              offsets: np.ndarray, preflop: np.ndarray, pool_cards: np.ndarray, pool_buckets: np.ndarray,
              regret: np.ndarray, strategy_sum: np.ndarray) -> None:
    per_thread = iterations // threads
    n = pool_cards.shape[0]
    for thread in prange(threads):
        np.random.seed(seed * 1_000_003 + thread)
        deck = np.empty(13, dtype=np.int64)
        buckets = np.empty((2, 4), dtype=np.int64)
        values = np.empty(4, dtype=np.int64)
        for i in range(per_thread):
            t = start + i * threads + thread + 1
            _deal_from_pool(np.random.randint(n), pool_cards, pool_buckets, preflop, deck, buckets, values)
            _walk(0, traverser_for(start, i, thread, threads), kind, actor, street, children, committed, folder,
                  offsets, buckets, values, regret, strategy_sum, float(t))


@njit(parallel=True)
def _run(iterations: int, start: int, seed: int, threads: int, kind: np.ndarray, actor: np.ndarray,
         street: np.ndarray, children: np.ndarray, committed: np.ndarray, folder: np.ndarray,
         offsets: np.ndarray, preflop: np.ndarray, flop_map: np.ndarray, turn_map: np.ndarray,
         regret: np.ndarray, strategy_sum: np.ndarray) -> None:
    per_thread = iterations // threads
    for thread in prange(threads):
        np.random.seed(seed * 1_000_003 + thread)
        deck = np.arange(52)
        buckets = np.empty((2, 4), dtype=np.int64)
        values = np.empty(4, dtype=np.int64)
        for i in range(per_thread):
            t = start + i * threads + thread + 1
            _deal(deck, preflop, flop_map, turn_map, buckets, values)
            _walk(0, traverser_for(start, i, thread, threads), kind, actor, street, children, committed, folder, offsets, buckets, values,
                  regret, strategy_sum, float(t))


class Trainer:
    """With a DealPool, deals and flop/turn/river equity buckets come from the pool; without one,
    deals are fresh and postflop buckets are the feature keys of the Abstraction."""

    def __init__(self, tree: PublicTree, abstraction: Abstraction, pool: DealPool | None = None):
        self.tree = tree
        self.abstraction = abstraction
        self.pool = pool
        self.bucket_counts = (abstraction.bucket_counts if pool is None
                              else (abstraction.bucket_counts[0], *pool.counts))
        self.offsets, size = layout(tree, self.bucket_counts)
        self.regret = np.zeros(size)
        self.strategy_sum = np.zeros(size)
        self.iterations = 0

    def run(self, iterations: int, *, threads: int = 1, seed: int = 0) -> float:
        """Run `iterations` (rounded down to a multiple of `threads`); returns iterations per second."""
        if iterations < threads or threads < 1:
            raise ValueError("need iterations >= threads >= 1")
        t = self.tree
        started = time.perf_counter()
        if self.pool is None:
            _run(iterations, self.iterations, seed, threads, t.kind, t.actor, t.street, t.children, t.committed,
                 t.folder, self.offsets, self.abstraction.preflop, self.abstraction.flop_map,
                 self.abstraction.turn_map, self.regret, self.strategy_sum)
        else:
            _run_pool(iterations, self.iterations, seed, threads, t.kind, t.actor, t.street, t.children,
                      t.committed, t.folder, self.offsets, self.abstraction.preflop, self.pool.cards,
                      self.pool.buckets, self.regret, self.strategy_sum)
        done = iterations // threads * threads
        self.iterations += done
        return done / max(time.perf_counter() - started, 1e-9)

    def _row(self, node: int, bucket: int) -> tuple[int, np.ndarray]:
        if self.tree.kind[node] != DECISION:
            raise ValueError("node is not a decision")
        if not 0 <= bucket < self.bucket_counts[self.tree.street[node]]:
            raise ValueError(f"bucket {bucket} out of range on street {self.tree.street[node]}")
        return int(self.offsets[node]) + SLOTS * bucket, self.tree.children[node] >= 0

    def average_policy(self, node: int, bucket: int) -> np.ndarray:
        base, legal = self._row(node, bucket)
        row = np.where(legal, self.strategy_sum[base:base + SLOTS], 0.0)
        total = row.sum()
        return row / total if total > 0 else legal / legal.sum()

    def visits(self, node: int, bucket: int) -> float:
        base, _ = self._row(node, bucket)
        return float(self.strategy_sum[base:base + SLOTS].sum())

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, regret=self.regret, strategy_sum=self.strategy_sum, iterations=self.iterations,
                 cap=self.tree.rules.cap)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path, tree: PublicTree, abstraction: Abstraction, pool: DealPool | None = None) -> Trainer:
        data = np.load(path)
        if int(data["cap"]) != tree.rules.cap:
            raise ValueError("checkpoint was trained with a different cap")
        trainer = cls(tree, abstraction, pool)
        if data["regret"].shape != trainer.regret.shape:
            raise ValueError("checkpoint does not match this abstraction")
        trainer.regret = data["regret"]
        trainer.strategy_sum = data["strategy_sum"]
        trainer.iterations = int(data["iterations"])
        return trainer
