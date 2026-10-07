"""Head-to-head match between two trained solutions on held-out deals.

Both solutions share the exact preflop classes; after the flop each maps a hand to its own buckets
from the same equity.hand_features (a solution with 3-number centroids reads only the random-hand
part), from the cards for a strength-bucket pool (o8_fl.strength, one-column placeholder centroids), or
from the exact-equity tables (o8_fl.exact_tables) for a pool built by them. For every deal the exact expected result is computed by walking the whole betting tree with
both average strategies, once with each solution in each seat, so only the choice of deals adds
noise. The deals come from a seed range the training pools never use.

    .venv/bin/python -m o8_fl.match --deals 1000000 \\
        --a tmp/o8_fl/run3 tmp/o8_fl/pool_v2.npz --b tmp/o8_fl/run2 tmp/o8_fl/pool.npz
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from numba import njit, prange

from .buckets import Abstraction
from .cli import ABSTRACTION
from .evaluator import omaha_high, omaha_low
from .game import Rules
from .pool import DealPool, assign, generate
from .ranges import RANGE, load_cdf
from .trainer import SLOTS, combo_index_native, layout, terminal_value
from .tree import DECISION, PublicTree

EVAL_SEED = 1_000_000_007  # training pools draw seeds from 1 up to about 16 million
DEALS = Path("tmp/o8_fl/match_deals.npz")
PRUNE = 1e-6


def held_out_deals(n: int, path: Path = DEALS, strong: Path = RANGE, chunk: int = 250_000) -> tuple[np.ndarray, np.ndarray]:
    """(cards, features) for n held-out deals, cached at `path`."""
    if path.exists():
        data = np.load(path)
        if len(data["cards"]) >= n:
            return data["cards"][:n], data["features"][:n].astype(np.float32)
    combos, cdf = load_cdf(strong)
    parts = [generate(min(chunk, n - start), EVAL_SEED + start, combos, cdf) for start in range(0, n, chunk)]
    cards = np.concatenate([p[0] for p in parts])
    features = np.concatenate([p[1] for p in parts])
    np.savez(path, cards=cards, features=features.astype(np.float16))
    return cards, features


def street_buckets(features: np.ndarray, centroids: tuple[np.ndarray, ...]) -> np.ndarray:
    """(n, 2, 3) bucket per player and street, using as many features as the centroids have."""
    n = features.shape[0]
    out = np.empty((n, 2, 3), dtype=np.int64)
    for street, c in enumerate(centroids):
        points = np.ascontiguousarray(features[:, :, street, :c.shape[1]].reshape(-1, c.shape[1]))
        out[:, :, street] = assign(points, np.ascontiguousarray(c, dtype=np.float32)).reshape(n, 2)
    return out


def average_policy_table(strategy_sum: np.ndarray, tree: PublicTree, offsets: np.ndarray,
                         bucket_counts: tuple[int, ...]) -> np.ndarray:
    """Normalised average strategy for every (node, bucket) row; unvisited rows play uniformly over legal actions."""
    rows = strategy_sum.reshape(-1, SLOTS)
    decisions = np.flatnonzero(tree.kind == DECISION)
    decisions = decisions[np.argsort(offsets[decisions])]
    per_node = np.array([bucket_counts[tree.street[d]] for d in decisions])
    legal = np.repeat(tree.children[decisions] >= 0, per_node, axis=0)
    total = rows.sum(axis=1, keepdims=True)
    uniform = legal / legal.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        policy = np.where(total > 0, rows / total, uniform)
    return np.where(legal, policy, 0.0).astype(np.float32).ravel()


@njit
def _value(node: int, kind: np.ndarray, actor: np.ndarray, street: np.ndarray, children: np.ndarray,
           committed: np.ndarray, folder: np.ndarray, a_seat: int, off_a: np.ndarray, pol_a: np.ndarray,
           bk_a: np.ndarray, off_b: np.ndarray, pol_b: np.ndarray, bk_b: np.ndarray, values: np.ndarray) -> float:
    """Expected net chips for seat 0 below `node` when solution A sits in `a_seat`."""
    if kind[node] != DECISION:
        return terminal_value(kind, committed, folder, node, 0, values[0], values[1], values[2], values[3])
    p = actor[node]
    s = street[node]
    if p == a_seat:
        base = off_a[node] + SLOTS * bk_a[p, s]
        policy = pol_a
    else:
        base = off_b[node] + SLOTS * bk_b[p, s]
        policy = pol_b
    total = 0.0
    for slot in range(SLOTS):
        child = children[node, slot]
        if child >= 0 and policy[base + slot] > PRUNE:
            total += policy[base + slot] * _value(child, kind, actor, street, children, committed, folder, a_seat,
                                                  off_a, pol_a, bk_a, off_b, pol_b, bk_b, values)
    return total


@njit(parallel=True)
def _play(cards: np.ndarray, preflop: np.ndarray, post_a: np.ndarray, post_b: np.ndarray, kind: np.ndarray,
          actor: np.ndarray, street: np.ndarray, children: np.ndarray, committed: np.ndarray, folder: np.ndarray,
          off_a: np.ndarray, pol_a: np.ndarray, off_b: np.ndarray, pol_b: np.ndarray) -> np.ndarray:
    """A's average result per hand over both seats, for every deal."""
    n = cards.shape[0]
    out = np.empty(n)
    for d in prange(n):
        board = cards[d, 8:13].astype(np.int64)
        values = np.empty(4, dtype=np.int64)
        bk_a = np.empty((2, 4), dtype=np.int64)
        bk_b = np.empty((2, 4), dtype=np.int64)
        for p in range(2):
            hole = cards[d, 4 * p:4 * p + 4].astype(np.int64)
            values[p] = omaha_high(hole, board)
            values[2 + p] = omaha_low(hole, board)
            bk_a[p, 0] = bk_b[p, 0] = preflop[combo_index_native(hole)]
            for s in range(3):
                bk_a[p, s + 1] = post_a[d, p, s]
                bk_b[p, s + 1] = post_b[d, p, s]
        a_first = _value(0, kind, actor, street, children, committed, folder, 0, off_a, pol_a, bk_a, off_b, pol_b,
                         bk_b, values)
        a_second = _value(0, kind, actor, street, children, committed, folder, 1, off_a, pol_a, bk_a, off_b, pol_b,
                          bk_b, values)
        out[d] = 0.5 * (a_first - a_second)
    return out


def load_solution(run: Path, pool_path: Path, tree: PublicTree, abstraction: Abstraction) -> dict:
    pool = DealPool.load(pool_path)
    counts = (abstraction.bucket_counts[0], *pool.counts)
    offsets, size = layout(tree, counts)
    data = np.load(run / "checkpoint.npz")
    strategy_sum = data["strategy_sum"]
    if strategy_sum.shape != (size,):
        raise ValueError(f"{run} does not match {pool_path}")
    return {"offsets": offsets, "policy": average_policy_table(strategy_sum, tree, offsets, counts),
            "centroids": pool.centroids, "iterations": int(data["iterations"])}


def within_bucket_spread(features: np.ndarray, buckets: np.ndarray, street: int) -> dict[str, float]:
    """Weighted mean within-bucket standard deviation of total equity, against a random hand and the strong range."""
    b = buckets[:, :, street].ravel()
    out = {}
    for name, cols in (("random", (0, 1)), ("strong", (3, 4))):
        x = features[:, :, street, cols[0]].ravel().astype(np.float64) + features[:, :, street, cols[1]].ravel()
        count = np.bincount(b)
        mean = np.bincount(b, x) / np.maximum(count, 1)
        var = np.bincount(b, x * x) / np.maximum(count, 1) - mean ** 2
        out[name] = round(float(np.sqrt(np.maximum(var, 0) @ count / count.sum())), 4)
    return out


def play(cards: np.ndarray, features: np.ndarray, a: dict, b: dict, tree: PublicTree,
         abstraction: Abstraction) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(A's result per deal, A's buckets, B's buckets)."""
    post_a, post_b = _buckets(cards, features, a), _buckets(cards, features, b)
    results = _play(cards, abstraction.preflop, post_a, post_b, tree.kind, tree.actor, tree.street, tree.children,
                    tree.committed, tree.folder, a["offsets"], a["policy"], b["offsets"], b["policy"])
    return results, post_a, post_b


def _buckets(cards: np.ndarray, features: np.ndarray, solution: dict) -> np.ndarray:
    from .exact_tables import deal_buckets, is_exact_pool
    if is_exact_pool(solution["centroids"]):  # exact-equity buckets: tables and river sums
        return deal_buckets(cards)
    if all(c.shape[1] == 1 for c in solution["centroids"]):  # strength buckets come from the cards
        from plo_premium_proof.tables import comb_table, five_card_ranks

        from .strength import deal_buckets
        return deal_buckets(np.ascontiguousarray(cards), five_card_ranks(), comb_table()).astype(np.int64)
    return street_buckets(features, solution["centroids"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--a", nargs=2, type=Path, required=True, metavar=("RUN", "POOL"))
    parser.add_argument("--b", nargs=2, type=Path, required=True, metavar=("RUN", "POOL"))
    parser.add_argument("--deals", type=int, default=1_000_000)
    parser.add_argument("--cap", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("tmp/o8_fl/match.json"))
    parser.add_argument("--cache", type=Path, default=DEALS, help="held-out deals and their features")
    parser.add_argument("--range", type=Path, default=RANGE)
    args = parser.parse_args(argv)
    abstraction = Abstraction.cached(ABSTRACTION)
    tree = PublicTree.build(Rules(cap=args.cap))
    started = time.perf_counter()
    cards, features = held_out_deals(args.deals, args.cache, args.range)
    a = load_solution(*args.a, tree, abstraction)
    b = load_solution(*args.b, tree, abstraction)
    results, post_a, post_b = play(cards, features, a, b, tree, abstraction)
    mean, se = float(results.mean()), float(results.std() / np.sqrt(len(results)))
    report = {"a": [str(p) for p in args.a], "b": [str(p) for p in args.b], "deals": len(results),
              "iterations": {"a": a["iterations"], "b": b["iterations"]},
              "a_bb_per_hand": round(mean, 5), "standard_error": round(se, 5),
              "a_mbb_per_hand": round(mean * 1000, 2), "z": round(mean / se, 2) if se > 0 else None,
              "spread": {name: {street: within_bucket_spread(features, post, s)
                                for s, street in enumerate(("flop", "turn", "river"))}
                         for name, post in (("a", post_a), ("b", post_b))},
              "seconds": round(time.perf_counter() - started)}
    args.out.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
