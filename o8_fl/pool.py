"""Deal pool with precomputed equity buckets for training.

Equity is far too slow to compute inside training, so it is computed once for a large pool of
deals: every player's equity.hand_features on the flop, turn and river, that is (high, low, spread)
against a random hand, where spread is the standard deviation of the final pot share, and (high,
low) against the strong range (ranges.py). k-means on those five numbers gives the buckets for each
street, and training samples whole deals from the pool.

    .venv/bin/python -m o8_fl.pool generate --deals 16000000      (resumable, 1M-deal chunks)
    .venv/bin/python -m o8_fl.pool cluster --flop 1000 --turn 2000 --river 2000
"""

from __future__ import annotations

import argparse
import dataclasses
import time
from pathlib import Path

import numpy as np
from numba import njit, prange

from .equity import FEATURES, hand_features
from .ranges import RANGE, load_cdf

POOL_DIR = Path("tmp/o8_fl/pool_v2")  # tmp/o8_fl/pool holds the older random-hand-only features
CHUNK = 1_000_000
STREET_KNOWN = (3, 4, 5)
# (runouts, random opponents per runout, strong-range opponents per runout) for flop, turn, river:
# 256 to 300 of each kind.
SAMPLES = ((32, 8, 8), (32, 8, 8), (1, 300, 300))


@njit(cache=True, parallel=True)
def generate(n: int, seed: int, combos: np.ndarray, cdf: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """n deals: cards (n, 13) as hole0, hole1, board; features (n, 2, 3, FEATURES), see hand_features."""
    cards = np.empty((n, 13), dtype=np.uint8)
    features = np.empty((n, 2, 3, FEATURES), dtype=np.float32)
    for d in prange(n):
        np.random.seed(seed + d)
        deck = np.arange(52)
        for i in range(13):
            j = i + np.random.randint(52 - i)
            deck[i], deck[j] = deck[j], deck[i]
            cards[d, i] = deck[i]
        board = deck[8:13].copy()
        for p in range(2):
            hole = deck[4 * p:4 * p + 4].copy()
            for s in range(3):
                features[d, p, s] = hand_features(hole, board, STREET_KNOWN[s], SAMPLES[s][0], SAMPLES[s][1],
                                                  SAMPLES[s][2], combos, cdf, (seed + d) * 7 + p * 3 + s)
    return cards, features


@njit(cache=True, parallel=True)
def assign(points: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    out = np.empty(points.shape[0], dtype=np.uint16)
    for i in prange(points.shape[0]):
        best, best_d = 0, 1e30
        for k in range(centroids.shape[0]):
            d = 0.0
            for j in range(points.shape[1]):
                diff = points[i, j] - centroids[k, j]
                d += diff * diff
            if d < best_d:
                best, best_d = k, d
        out[i] = best
    return out


@njit(cache=True)
def _plus_plus(points: np.ndarray, k: int, seed: int) -> np.ndarray:
    """k-means++ seeding: each new centre is drawn with probability proportional to squared distance."""
    np.random.seed(seed)
    n, dim = points.shape
    centroids = np.empty((k, dim), dtype=np.float32)
    centroids[0] = points[np.random.randint(n)]
    nearest = np.full(n, 1e30)
    for c in range(1, k):
        total = 0.0
        for i in range(n):
            d = 0.0
            for j in range(dim):
                diff = points[i, j] - centroids[c - 1, j]
                d += diff * diff
            if d < nearest[i]:
                nearest[i] = d
            total += nearest[i]
        target = np.random.random() * total
        pick = n - 1
        for i in range(n):
            target -= nearest[i]
            if target <= 0:
                pick = i
                break
        centroids[c] = points[pick]
    return centroids


@njit(cache=True)
def _update(points: np.ndarray, labels: np.ndarray, centroids: np.ndarray) -> float:
    k, dim = centroids.shape
    sums = np.zeros((k, dim))
    counts = np.zeros(k)
    for i in range(points.shape[0]):
        counts[labels[i]] += 1
        for j in range(dim):
            sums[labels[i], j] += points[i, j]
    moved = 0.0
    for c in range(k):
        if counts[c] == 0:
            continue
        for j in range(dim):
            new = sums[c, j] / counts[c]
            moved = max(moved, abs(new - centroids[c, j]))
            centroids[c, j] = new
    return moved


def kmeans(points: np.ndarray, k: int, iterations: int = 30, seed: int = 0) -> np.ndarray:
    """Lloyd's k-means with k-means++ seeding; returns centroids sorted by total equity, then high share."""
    points = np.ascontiguousarray(points, dtype=np.float32)
    centroids = _plus_plus(points, k, seed)
    for _ in range(iterations):
        if _update(points, assign(points, centroids), centroids) < 1e-5:
            break
    order = np.lexsort((centroids[:, 0], centroids[:, 0] + centroids[:, 1]))
    return centroids[order]


@dataclasses.dataclass(frozen=True)
class DealPool:
    cards: np.ndarray  # (n, 13) uint8
    buckets: np.ndarray  # (n, 2, 3) uint16: player, street (flop, turn, river)
    centroids: tuple[np.ndarray, np.ndarray, np.ndarray]

    @property
    def counts(self) -> tuple[int, int, int]:
        return tuple(len(c) for c in self.centroids)

    def save(self, path: Path) -> None:
        np.savez(path, cards=self.cards, buckets=self.buckets, flop=self.centroids[0], turn=self.centroids[1],
                 river=self.centroids[2])

    @classmethod
    def load(cls, path: Path) -> DealPool:
        data = np.load(path)
        return cls(data["cards"], data["buckets"], (data["flop"], data["turn"], data["river"]))


def chunk_paths(directory: Path = POOL_DIR) -> list[Path]:
    return sorted(directory.glob("chunk_*.npz"))


def generate_chunks(total: int, directory: Path = POOL_DIR, seed: int = 1, strong: Path = RANGE) -> None:
    combos, cdf = load_cdf(strong)
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(total // CHUNK):
        path = directory / f"chunk_{index:03d}.npz"
        if path.exists():
            continue
        started = time.perf_counter()
        cards, features = generate(CHUNK, seed + index * CHUNK, combos, cdf)
        np.savez(path.with_suffix(".tmp.npz"), cards=cards, features=features.astype(np.float16))
        path.with_suffix(".tmp.npz").replace(path)
        print(f"{path.name}: {time.perf_counter() - started:.0f}s", flush=True)


def build_pool(sizes: tuple[int, int, int], directory: Path = POOL_DIR, sample: int = 2_000_000,
               seed: int = 0) -> DealPool:
    chunks = [np.load(p) for p in chunk_paths(directory)]
    cards = np.concatenate([c["cards"] for c in chunks])
    features = np.concatenate([c["features"] for c in chunks]).astype(np.float32)
    rng = np.random.default_rng(seed)
    buckets = np.empty((len(cards), 2, 3), dtype=np.uint16)
    centroids = []
    for street, k in enumerate(sizes):
        points = features[:, :, street, :].reshape(-1, features.shape[-1])
        picked = points[rng.choice(len(points), size=min(sample, len(points)), replace=False)]
        started = time.perf_counter()
        c = kmeans(picked, k, seed=seed + street)
        buckets[:, :, street] = assign(points, c).reshape(len(cards), 2)
        centroids.append(c)
        print(f"street {street + 1}: {k} buckets in {time.perf_counter() - started:.0f}s", flush=True)
    return DealPool(cards, buckets, tuple(centroids))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--deals", type=int, default=16_000_000)
    c = sub.add_parser("cluster")
    c.add_argument("--flop", type=int, default=1000)
    c.add_argument("--turn", type=int, default=2000)
    c.add_argument("--river", type=int, default=2000)
    c.add_argument("--out", type=Path, default=POOL_DIR.parent / "pool.npz")
    args = parser.parse_args(argv)
    if args.command == "generate":
        generate_chunks(args.deals)
    else:
        build_pool((args.flop, args.turn, args.river)).save(args.out)


if __name__ == "__main__":
    main()
