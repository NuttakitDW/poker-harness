"""Exact-equity buckets for O8 (exact.py) on every street: fitting, flop and turn tables, and the training pool.

A bucket is k-means on the five exact features, read through a lookup grid so it costs one table
lookup: each feature is cut at sample quantiles into a few bins, and every grid cell holds the
nearest centroid to the sample points that fell in it (or to its centre). The browser does the
same for the river (o8-river.js reads river-grid.json).

One pass per library flop (all 1,755) computes river sums for every turn+river pair once, which gives
every hand's turn features (average over rivers) and flop features (average over turns). The pass
writes the flop table and the 49 turn tables of that flop and fills in the pool deals that run out on
it, so the training pool and the page use the same buckets.

    .venv/bin/python -m o8_fl.exact_tables sample --flops 20          (features of random flops)
    .venv/bin/python -m o8_fl.exact_tables fit                        (k-means + grids, grids.npz)
    .venv/bin/python -m o8_fl.exact_tables deals                      (pool deals in library-flop suits)
    .venv/bin/python -m o8_fl.exact_tables build --workers 10         (tables + pool, resumable per flop)
    .venv/bin/python -m o8_fl.exact_tables pool                       (pool_v4.npz from the per-flop parts)
"""

from __future__ import annotations

import argparse
import gzip
import itertools
import json
import os
import time
from pathlib import Path

import numpy as np
from numba import njit, prange

from .buckets import Abstraction
from .cli import ABSTRACTION
from .exact import colex_table, river_sums_fast, strong_weights
from .flops import ALL_FLOPS, class_order, select_flops
from .pool import DealPool, assign, kmeans
from .ranges import COMBOS

ROOT = Path("tmp/o8_fl/exact")
SIZES = (1000, 2000, 2000)  # flop, turn, river buckets, as pool_v2
# Grid bins per feature: high, low, spread against a random hand, strong high, strong low.
BINS = (64, 32, 10, 48, 24)
NO_BUCKET = 65535
PERMS = np.array(list(itertools.permutations(range(4))), dtype=np.int64)


# ---------- features ----------

@njit(cache=True)  # pragma: no cover - compiled native code
def _river_features(sums: np.ndarray, k: int, out: np.ndarray) -> bool:
    n = sums[k, 0]
    if n <= 0:  # the hand shares a card with the board
        return False
    # first-order card removal can leave a hopeless hand's share a hair below zero; kept as is, the
    # browser computes the same value
    hi = sums[k, 1] / (4.0 * n)
    lo = sums[k, 2] / (4.0 * n)
    out[0] = hi
    out[1] = lo
    out[2] = sums[k, 3] / (16.0 * n)  # mean square; the spread is taken at the end
    out[3] = sums[k, 5] / (4.0 * sums[k, 4])
    out[4] = sums[k, 6] / (4.0 * sums[k, 4])
    return True


@njit(cache=True)  # pragma: no cover - compiled native code
def finish(means: np.ndarray) -> np.ndarray:
    """(high, low, mean square, strong high, strong low) -> features with the spread in place of the square."""
    out = means.copy()
    for k in range(means.shape[0]):
        total = means[k, 0] + means[k, 1]
        out[k, 2] = np.sqrt(max(means[k, 2] - total * total, 0.0))
    return out


@njit(cache=True)  # pragma: no cover - compiled native code
def flop_pass(flop: np.ndarray, hands: np.ndarray, weights: np.ndarray, colex: np.ndarray,
              req_pair: np.ndarray, req_hand: np.ndarray, req_out: np.ndarray):
    """Turn means (52, n, 5) by turn card, flop means (n, 5), and river means for requested (pair, hand) rows.

    req_pair holds t * 52 + r (t < r) sorted; req_out gets the river means of hand req_hand there."""
    n = hands.shape[0]
    turn_sum = np.zeros((52, n, 5))
    turn_cnt = np.zeros((52, n), dtype=np.int32)
    on = np.zeros(52, dtype=np.bool_)
    for c in flop:
        on[c] = True
    board = np.empty(5, dtype=np.int64)
    board[:3] = flop
    f = np.empty(5)
    r_at = 0
    for t in range(52):
        if on[t]:
            continue
        for r in range(t + 1, 52):
            if on[r]:
                continue
            board[3], board[4] = t, r
            sums = river_sums_fast(board, hands, weights, colex)
            for k in range(n):
                if _river_features(sums, k, f):
                    for m in range(5):
                        turn_sum[t, k, m] += f[m]
                        turn_sum[r, k, m] += f[m]
                    turn_cnt[t, k] += 1
                    turn_cnt[r, k] += 1
            key = t * 52 + r
            while r_at < req_pair.shape[0] and req_pair[r_at] < key:
                r_at += 1
            while r_at < req_pair.shape[0] and req_pair[r_at] == key:
                _river_features(sums, req_hand[r_at], req_out[r_at])
                r_at += 1
    flop_sum = np.zeros((n, 5))
    flop_cnt = np.zeros(n, dtype=np.int32)
    for t in range(52):
        for k in range(n):
            if turn_cnt[t, k] > 0:
                for m in range(5):
                    turn_sum[t, k, m] /= turn_cnt[t, k]
                    flop_sum[k, m] += turn_sum[t, k, m]
                flop_cnt[k] += 1
    for k in range(n):
        if flop_cnt[k] > 0:
            for m in range(5):
                flop_sum[k, m] /= flop_cnt[k]
    return turn_sum, turn_cnt, flop_sum, flop_cnt


# ---------- grids ----------

@njit(cache=True)  # pragma: no cover - compiled native code
def cell_of(x: np.ndarray, edges: np.ndarray, bins: np.ndarray) -> int:
    """Grid cell of one feature vector; edges[d, :bins[d] - 1] are the inner cut points of feature d."""
    cell = 0
    for d in range(5):
        b = np.searchsorted(edges[d, :bins[d] - 1], x[d], side="right")
        cell = cell * bins[d] + b
    return cell


@njit(cache=True)  # pragma: no cover - compiled native code
def lookup(features: np.ndarray, valid: np.ndarray, edges: np.ndarray, bins: np.ndarray, table: np.ndarray) -> np.ndarray:
    out = np.full(features.shape[0], NO_BUCKET, dtype=np.uint16)
    for k in range(features.shape[0]):
        if valid[k]:
            out[k] = table[cell_of(features[k], edges, bins)]
    return out


def fit_grid(points: np.ndarray, k: int, bins=BINS, seed: int = 0) -> dict:
    """k-means centroids and the lookup grid (edges at sample quantiles, a centroid per cell)."""
    points = np.ascontiguousarray(points, dtype=np.float64)
    centroids = kmeans(points.astype(np.float32), k, seed=seed)
    bins = np.asarray(bins, dtype=np.int64)
    edges = np.full((5, int(bins.max()) - 1), np.inf)
    for d in range(5):
        cuts = np.unique(np.quantile(points[:, d], np.linspace(0, 1, bins[d] + 1)[1:-1]))
        edges[d, :len(cuts)] = cuts
        bins[d] = len(cuts) + 1
    cells = int(np.prod(bins))
    cell = np.array([cell_of(p, edges, bins) for p in points]) if len(points) < 50_000 else _cells(points, edges, bins)
    sums = np.zeros((cells, 5))
    np.add.at(sums, cell, points)
    counts = np.bincount(cell, minlength=cells)
    centres = _centres(edges, bins, points)
    reps = np.where(counts[:, None] > 0, sums / np.maximum(counts, 1)[:, None], centres)
    table = assign(np.ascontiguousarray(reps, dtype=np.float32), centroids).astype(np.uint16)
    return {"centroids": centroids, "edges": edges, "bins": bins, "table": table}


@njit(cache=True)  # pragma: no cover - compiled native code
def _cells(points: np.ndarray, edges: np.ndarray, bins: np.ndarray) -> np.ndarray:
    out = np.empty(points.shape[0], dtype=np.int64)
    for k in range(points.shape[0]):
        out[k] = cell_of(points[k], edges, bins)
    return out


def _centres(edges: np.ndarray, bins: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Middle of every cell (outer bins run to the sample min / max)."""
    mids = []
    for d in range(5):
        cuts = np.concatenate([[points[:, d].min()], edges[d, :bins[d] - 1], [points[:, d].max()]])
        mids.append((cuts[:-1] + cuts[1:]) / 2)
    grid = np.stack(np.meshgrid(*mids, indexing="ij"), axis=-1)
    return grid.reshape(-1, 5)


def load_grids(path: Path = ROOT / "grids.npz") -> list[dict]:
    data = np.load(path)
    return [{key: data[f"{street}_{key}"] for key in ("centroids", "edges", "bins", "table")}
            for street in ("flop", "turn", "river")]


# ---------- the pass over flops ----------

def _setup() -> dict:
    abstraction = Abstraction.cached(ABSTRACTION)
    order = class_order(abstraction)
    position = np.empty(len(order), dtype=np.int64)
    position[order] = np.arange(len(order))  # combo index -> row in the tables
    return {"hands": np.ascontiguousarray(COMBOS[order]), "position": position, "weights": strong_weights(),
            "colex": colex_table()}


def _write(path: Path, buckets: np.ndarray) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(buckets.astype("<u2").tobytes(), 9))
    tmp.replace(path)


_STATE: dict = {}


def _init() -> None:
    _STATE.update(_setup())


def sample(flops: int, workers: int, seed: int = 0) -> None:
    """Features of every street on a few random library flops, for fitting the grids."""
    from multiprocessing import Pool
    picks = np.random.default_rng(seed).choice(ALL_FLOPS, size=flops, replace=False)
    with Pool(workers, initializer=_init) as pool:
        for line in pool.imap_unordered(_sample_one, [int(i) for i in picks]):
            print(line, flush=True)


def _sample_one(index: int, per_flop: int = 200_000) -> str:
    s = _STATE
    rng = np.random.default_rng(index)
    library = select_flops(ALL_FLOPS, 0)
    out = ROOT / "sample"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"flop-{index:04d}.npz"
    if path.exists():
        return f"{index}: done before"
    if True:
        started = time.perf_counter()
        flop = np.asarray(library[index], dtype=np.int64)
        n = len(s["hands"])
        # river samples: a random hand on a random turn+river pair per request
        live = [c for c in range(52) if c not in flop]
        pairs, hands = [], []
        for _ in range(per_flop // 20):
            t, r = sorted(rng.choice(live, 2, replace=False))
            pairs.append(t * 52 + r)
            hands.append(rng.integers(n))
        order = np.argsort(pairs, kind="stable")
        req_pair, req_hand = np.asarray(pairs)[order], np.asarray(hands)[order]
        req_out = np.full((len(req_pair), 5), np.nan)
        turn, turn_cnt, flop_means, flop_cnt = flop_pass(flop, s["hands"], s["weights"], s["colex"], req_pair,
                                                         req_hand, req_out)
        pick = rng.choice(n, size=per_flop, replace=False)
        turn_pts = []
        for t in live:
            rows = pick[turn_cnt[t, pick] > 0]
            turn_pts.append(turn[t, rows[: per_flop // len(live)]])
        np.savez(path, flop=finish(flop_means[pick[flop_cnt[pick] > 0]]), turn=finish(np.concatenate(turn_pts)),
                 river=finish(req_out[~np.isnan(req_out[:, 0])]))
        return f"sample flop {index}: {time.perf_counter() - started:.0f}s"


def fit() -> None:
    parts = [np.load(p) for p in sorted((ROOT / "sample").glob("flop-*.npz"))]
    saved = {}
    for street, k in zip(("flop", "turn", "river"), SIZES):
        points = np.concatenate([p[street] for p in parts])
        rng = np.random.default_rng(1)
        points = points[rng.choice(len(points), size=min(len(points), 2_000_000), replace=False)]
        started = time.perf_counter()
        grid = fit_grid(points, k)
        for key, value in grid.items():
            saved[f"{street}_{key}"] = value
        cells = int(np.prod(grid["bins"]))
        print(f"{street}: {len(points):,} points, {k} buckets, {cells:,} cells, {time.perf_counter() - started:.0f}s",
              flush=True)
    np.savez(ROOT / "grids.npz", **saved)



# ---------- the training pool ----------

def flop_maps() -> tuple[np.ndarray, np.ndarray]:
    """For every sorted flop (a*2704 + b*52 + c): its library id and the suit permutation into it."""
    library = {tuple(f): i for i, f in enumerate(select_flops(ALL_FLOPS, 0))}
    lib = np.full(52 ** 3, -1, dtype=np.int32)
    perm = np.full(52 ** 3, -1, dtype=np.int8)
    for flop in itertools.combinations(range(52), 3):
        best = None
        for p_index, p in enumerate(PERMS):
            mapped = tuple(sorted(int((c >> 2) * 4 + p[c & 3]) for c in flop))
            if best is None or mapped < best[0]:
                best = (mapped, p_index)
        key = flop[0] * 2704 + flop[1] * 52 + flop[2]
        lib[key], perm[key] = library[best[0]], best[1]
    return lib, perm


@njit(cache=True)  # pragma: no cover - compiled native code
def map_deals(cards: np.ndarray, lib: np.ndarray, perm: np.ndarray, perms: np.ndarray, colex: np.ndarray,
              position: np.ndarray):
    """Each deal in its library flop's suits: (flop id, turn card, river card, table rows of both hands)."""
    n = cards.shape[0]
    flop_id = np.empty(n, dtype=np.int32)
    turn = np.empty(n, dtype=np.int8)
    river = np.empty(n, dtype=np.int8)
    rows = np.empty((n, 2), dtype=np.int32)
    f = np.empty(3, dtype=np.int64)
    h = np.empty(4, dtype=np.int64)
    for d in range(n):
        for i in range(3):
            f[i] = cards[d, 8 + i]
        f.sort()
        key = f[0] * 2704 + f[1] * 52 + f[2]
        p = perms[perm[key]]
        flop_id[d] = lib[key]
        turn[d] = (cards[d, 11] >> 2) * 4 + p[cards[d, 11] & 3]
        river[d] = (cards[d, 12] >> 2) * 4 + p[cards[d, 12] & 3]
        for player in range(2):
            for i in range(4):
                c = cards[d, 4 * player + i]
                h[i] = (c >> 2) * 4 + p[c & 3]
            h.sort()
            rows[d, player] = position[colex[h[0], h[1], h[2], h[3]]]
    return flop_id, turn, river, rows


def prepare_deals(source: Path = Path("tmp/o8_fl/pool_v2.npz")) -> None:
    s = _setup()
    cards = np.ascontiguousarray(np.load(source)["cards"])
    lib, perm = flop_maps()
    flop_id, turn, river, rows = map_deals(cards, lib, perm, PERMS, s["colex"], s["position"])
    order = np.argsort(flop_id, kind="stable")
    offsets = np.searchsorted(flop_id[order], np.arange(ALL_FLOPS + 1))
    np.savez(ROOT / "deals.npz", order=order, offsets=offsets, turn=turn, river=river, rows=rows)
    print(f"{len(cards):,} deals over {np.count_nonzero(np.diff(offsets))} flops", flush=True)


def build(workers: int) -> None:
    from multiprocessing import Pool
    (ROOT / "tables").mkdir(parents=True, exist_ok=True)
    (ROOT / "parts").mkdir(parents=True, exist_ok=True)
    todo = [i for i in range(ALL_FLOPS) if not (ROOT / "parts" / f"flop-{i:04d}.npz").exists()]
    with Pool(workers, initializer=_init_build) as pool:
        for line in pool.imap_unordered(_build_one, todo):
            print(line, flush=True)


def _init_build() -> None:
    _init()
    _STATE["grids"] = load_grids()
    _STATE["deals"] = dict(np.load(ROOT / "deals.npz"))
    _STATE["library"] = select_flops(ALL_FLOPS, 0)


def _bucket(grid: dict, means: np.ndarray, valid: np.ndarray) -> np.ndarray:
    return lookup(finish(means), valid, grid["edges"], grid["bins"].astype(np.int64), grid["table"])


def _build_one(index: int) -> str:
    s = _STATE
    started = time.perf_counter()
    flop_grid, turn_grid, river_grid = s["grids"]
    deals = s["deals"]
    mine = deals["order"][deals["offsets"][index]:deals["offsets"][index + 1]]
    t, r = deals["turn"][mine].astype(np.int64), deals["river"][mine].astype(np.int64)
    keys = np.minimum(t, r) * 52 + np.maximum(t, r)
    req_pair = np.repeat(keys, 2)
    req_hand = deals["rows"][mine].reshape(-1).astype(np.int64)
    order = np.argsort(req_pair, kind="stable")
    req_out = np.full((len(order), 5), np.nan)  # stays NaN only if the pass never reached the request
    flop = np.asarray(s["library"][index], dtype=np.int64)
    turn, turn_cnt, flop_means, flop_cnt = flop_pass(flop, s["hands"], s["weights"], s["colex"], req_pair[order],
                                                     req_hand[order], req_out)
    flop_b = _bucket(flop_grid, flop_means, flop_cnt > 0)
    _write(ROOT / "tables" / f"flop-{index:04d}.bin", flop_b)
    turn_b = np.full((52, len(flop_b)), NO_BUCKET, dtype=np.uint16)
    for card in range(52):
        if card in flop:
            continue
        turn_b[card] = _bucket(turn_grid, turn[card], turn_cnt[card] > 0)
        _write(ROOT / "tables" / f"turn-{index:04d}-{card:02d}.bin", turn_b[card])
    river_means = np.empty_like(req_out)
    river_means[order] = req_out
    river_b = _bucket(river_grid, river_means, ~np.isnan(river_means[:, 0])).reshape(-1, 2)
    rows = deals["rows"][mine]
    buckets = np.empty((len(mine), 2, 3), dtype=np.uint16)
    buckets[:, :, 0] = flop_b[rows]
    buckets[:, :, 1] = turn_b[t[:, None], rows]
    buckets[:, :, 2] = river_b
    np.savez(ROOT / "parts" / f"flop-{index:04d}.npz", deals=mine, buckets=buckets)
    return f"flop {index}: {len(mine):,} deals, {time.perf_counter() - started:.0f}s"


def assemble(source: Path = Path("tmp/o8_fl/pool_v2.npz"), out: Path = Path("tmp/o8_fl/pool_v4.npz")) -> None:
    cards = np.load(source)["cards"]
    buckets = np.full((len(cards), 2, 3), NO_BUCKET, dtype=np.uint16)
    for path in sorted((ROOT / "parts").glob("flop-*.npz")):
        part = np.load(path)
        buckets[part["deals"]] = part["buckets"]
    missing = int((buckets == NO_BUCKET).any(axis=(1, 2)).sum())
    if missing:
        raise SystemExit(f"{missing:,} deals have no bucket; build every flop first")
    grids = load_grids()
    DealPool(cards, buckets, tuple(g["centroids"] for g in grids)).save(out)
    print(f"{out}: {len(cards):,} deals", flush=True)



@njit(cache=True, parallel=True)  # pragma: no cover - compiled native code
def _river_means(cards: np.ndarray, weights: np.ndarray, colex: np.ndarray) -> np.ndarray:
    n = cards.shape[0]
    out = np.full((n, 2, 5), np.nan)
    for d in prange(n):
        board = cards[d, 8:13].astype(np.int64)
        hands = np.empty((2, 4), dtype=np.int64)
        for p in range(2):
            hands[p] = np.sort(cards[d, 4 * p:4 * p + 4].astype(np.int64))
        sums = river_sums_fast(board, hands, weights, colex)
        for p in range(2):
            _river_features(sums, p, out[d, p])
    return out


def deal_buckets(cards: np.ndarray) -> np.ndarray:
    """(n, 2, 3) exact buckets for any deals (hole0, hole1, board): flop and turn from the tables, river computed."""
    s = _setup()
    grids = load_grids()
    lib, perm = flop_maps()
    flop_id, turn, _, rows = map_deals(np.ascontiguousarray(cards), lib, perm, PERMS, s["colex"], s["position"])
    out = np.empty((len(cards), 2, 3), dtype=np.int64)
    for index in np.unique(flop_id):
        mine = np.flatnonzero(flop_id == index)
        table = np.frombuffer(gzip.decompress((ROOT / "tables" / f"flop-{index:04d}.bin").read_bytes()), "<u2")
        out[mine, :, 0] = table[rows[mine]]
        for card in np.unique(turn[mine]):
            these = mine[turn[mine] == card]
            table = np.frombuffer(gzip.decompress((ROOT / "tables" / f"turn-{index:04d}-{card:02d}.bin").read_bytes()),
                                  "<u2")
            out[these, :, 1] = table[rows[these]]
    means = _river_means(np.ascontiguousarray(cards), s["weights"], s["colex"]).reshape(-1, 5)
    out[:, :, 2] = _bucket(grids[2], means, ~np.isnan(means[:, 0])).reshape(-1, 2)
    return out


def is_exact_pool(centroids) -> bool:
    """True when a pool's centroids are this module's (its buckets come from deal_buckets)."""
    path = ROOT / "grids.npz"
    if not path.exists():
        return False
    return all(np.array_equal(c, g["centroids"]) for c, g in zip(centroids, load_grids(path)))



def export_river(out: Path) -> None:
    """o8-river-grid.json (cut points, bins, strong-range weight per class) and o8-river-table.bin for o8-river.js."""
    grid = load_grids()[2]
    abstraction = Abstraction.cached(ABSTRACTION)
    weights = strong_weights()
    per_class = np.zeros(len(abstraction.preflop_names), dtype=np.int64)
    per_class[abstraction.preflop] = weights  # equal within a class
    bins = [int(b) for b in grid["bins"]]
    meta = {"bins": bins, "edges": [[float(x) for x in grid["edges"][d, :bins[d] - 1]] for d in range(5)],
            "weights": per_class.tolist()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "o8-river-grid.json").write_text(json.dumps(meta, separators=(",", ":")))
    _write(out / "o8-river-table.bin", grid["table"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--flops", type=int, default=20)
    s.add_argument("--workers", type=int, default=10)
    sub.add_parser("fit")
    sub.add_parser("deals")
    b = sub.add_parser("build")
    b.add_argument("--workers", type=int, default=10)
    sub.add_parser("pool")
    args = parser.parse_args(argv)
    if args.command == "sample":
        sample(args.flops, args.workers)
    elif args.command == "fit":
        fit()
    elif args.command == "deals":
        prepare_deals()
    elif args.command == "build":
        build(args.workers)
    else:
        assemble()


if __name__ == "__main__":
    main()
