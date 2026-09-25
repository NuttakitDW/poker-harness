"""The Oddsmaker: how often each hand class wins against the others, worked out once, offline.

Two tables go into every solve:

* e2[h, g]        heads-up equity of class h vs class g, averaged over every compatible
                  combo pair (exact, from the pokerkit-checked cache in tmp/equity.sqlite).
* eq3[h, g, k]    3-way all-in equity of h vs g and k (ties split).
  pw[h, g, k]     equity of h vs g in a side pot, on the same board, with k's cards dead.
                  Side pots need this finish order; plain e2 is not enough.

The 3-way tables are Monte Carlo: `samples` random deals per class triple.
All tables are cached under tmp/ because they depend on nothing but the deck.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import functools
import itertools
import os
import sys
import time
from pathlib import Path

import numpy as np

from pushfold import hands

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import equity_eval as ev  # noqa: E402

E2_FILE = ROOT / "tmp" / "pushfold-e2.npz"
E3_FILE = ROOT / "tmp" / "pushfold-e3.npz"
SAMPLES = 2000
SEED = 20260924
N = len(hands.CLASSES)

_HOLE_COLUMN = np.full((13, 13), -1, dtype=np.int16)
for (low, high), column in ev._HOLE_INDEX.items():
    _HOLE_COLUMN[low, high] = column


# ---------------------------------------------------------------- evaluator

def strength(holes: np.ndarray, boards: np.ndarray) -> np.ndarray:
    """7-card strength of holes (n, 2) on boards (n, 5), row by row. Bigger is better.

    Same scale as pokerkit's Entry.index, via the lookup tables in equity_eval.
    """
    table = ev.tables()
    board_ranks = boards // 4
    keys = np.prod(ev._PRIMES[board_ranks], axis=1)
    rows = np.searchsorted(table["board_keys"], keys)
    hole_ranks = np.sort(holes // 4, axis=1)
    best = table["unsuited"][rows, _HOLE_COLUMN[hole_ranks[:, 0], hole_ranks[:, 1]]].astype(np.int32)
    board_bits = np.int32(1) << board_ranks.astype(np.int32)
    hole_bits = np.int32(1) << (holes // 4).astype(np.int32)
    for suit in range(4):
        mask = (np.where(boards % 4 == suit, board_bits, 0).sum(axis=1)
                | np.where(holes % 4 == suit, hole_bits, 0).sum(axis=1))
        best = np.maximum(best, table["flush"][mask])
    return best


# ---------------------------------------------------------------- tables

@dataclasses.dataclass(frozen=True)
class Tables:
    e2: np.ndarray        # (169, 169)
    eq3: np.ndarray       # (169, 169, 169)
    pw: np.ndarray        # (169, 169, 169)
    possible: np.ndarray  # (169, 169, 169) bool: can these three classes be dealt together
    samples: int


def build_e2() -> np.ndarray:
    """Collapse the exact combo-level cache into a 169x169 table weighted by combos."""
    import equity  # scripts/voice/equity.py, pokerkit-exact preflop equity

    first, second = np.triu_indices(len(hands.COMBOS), k=1)
    a, b = hands.COMBOS[first], hands.COMBOS[second]
    apart = ~((a[:, :, None] == b[:, None, :]).any(axis=(1, 2)))
    first, second = first[apart], second[apart]
    matchups = np.stack([hands.COMBOS[first], hands.COMBOS[second]], axis=1)
    known = equity.MEMO.load()
    keys = equity.canonical_keys(matchups, ())
    missing = sum(key not in known for key in keys)
    if missing:
        raise RuntimeError(f"{missing} matchups missing from {equity.MEMO_FILE}; "
                           "run scripts/build_equity_cache.py first")
    first_equity = np.array([known[key].equity[0] for key in keys])
    ci, cj = hands.CLASS_OF[first], hands.CLASS_OF[second]
    sums = np.zeros((N, N))
    np.add.at(sums, (ci, cj), first_equity)
    np.add.at(sums, (cj, ci), 1.0 - first_equity)
    return sums / hands.W


def _class_combos() -> tuple[np.ndarray, np.ndarray]:
    padded = np.zeros((N, 12, 2), dtype=np.int16)
    for cls in range(N):
        mine = hands.COMBOS[hands.CLASS_OF == cls]
        padded[cls, :len(mine)] = mine
    return padded, hands.COUNTS.astype(np.int64)


def rank_feasible(triple: tuple[int, int, int]) -> bool:
    """Three classes can share one deck only if no rank is needed more than 4 times."""
    need = np.zeros(13, dtype=int)
    for cls in triple:
        label = hands.CLASSES[cls]
        for rank in label[:2]:
            need[hands.RANKS.index(rank)] += 1
    return bool(need.max() <= 4)


def _deal(triples: np.ndarray, samples: int, rng: np.random.Generator):
    """Random compatible holes (t, s, 3, 2) and boards (t, s, 5) for each class triple."""
    padded, counts = _class_combos()
    t = len(triples)
    holes = np.zeros((t, samples, 3, 2), dtype=np.int16)
    todo = np.ones((t, samples), dtype=bool)
    while todo.any():
        rows, cols = np.nonzero(todo)
        picks = (rng.random((len(rows), 3)) * counts[triples[rows]]).astype(np.int64)
        cards = padded[triples[rows][:, :, None], picks[:, :, None], np.arange(2)]
        flat = cards.reshape(len(rows), 6)
        clash = (np.sort(flat, axis=1)[:, 1:] == np.sort(flat, axis=1)[:, :-1]).any(axis=1)
        holes[rows[~clash], cols[~clash]] = cards[~clash]
        todo[rows[~clash], cols[~clash]] = False
    boards = np.zeros((t, samples, 5), dtype=np.int16)
    used = np.zeros((t, samples), dtype=np.int64)
    for card in holes.reshape(t, samples, 6).transpose(2, 0, 1):
        used |= np.int64(1) << card.astype(np.int64)
    for slot in range(5):
        pending = np.ones((t, samples), dtype=bool)
        while pending.any():
            rows, cols = np.nonzero(pending)
            card = rng.integers(0, 52, size=len(rows)).astype(np.int64)
            free = (used[rows, cols] >> card & 1) == 0
            r, c, k = rows[free], cols[free], card[free]
            boards[r, c, slot] = k
            used[r, c] |= np.int64(1) << k
            pending[r, c] = False
    return holes, boards


def _chunk(job: tuple[np.ndarray, int, int]) -> np.ndarray:
    """Per triple: 3-way equity of each seat, then pairwise wins a>b, a>c, b>c (ties half)."""
    triples, samples, seed = job
    rng = np.random.default_rng(seed)
    holes, boards = _deal(triples, samples, rng)
    t = len(triples)
    flat_boards = boards.reshape(-1, 5)
    s = np.stack([strength(holes[:, :, seat].reshape(-1, 2), flat_boards)
                  for seat in range(3)], axis=1).reshape(t, samples, 3)
    top = s == s.max(axis=2, keepdims=True)
    eq3 = (top / top.sum(axis=2, keepdims=True)).mean(axis=1)
    pairs = [(0, 1), (0, 2), (1, 2)]
    pw = np.stack([((s[:, :, x] > s[:, :, y]) + 0.5 * (s[:, :, x] == s[:, :, y])).mean(axis=1)
                   for x, y in pairs], axis=1)
    return np.concatenate([eq3, pw], axis=1)


def build_three_way(samples: int = SAMPLES, workers: int | None = None, chunk: int = 256,
                    log=print) -> Tables:
    triples = np.array([t for t in itertools.combinations_with_replacement(range(N), 3)
                        if rank_feasible(t)], dtype=np.int64)
    jobs = [(triples[i:i + chunk], samples, SEED + i) for i in range(0, len(triples), chunk)]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    began = time.perf_counter()
    log(f"{len(triples):,} class triples x {samples:,} deals on {workers} cores")
    with concurrent.futures.ProcessPoolExecutor(workers) as pool:
        parts = []
        for done, part in enumerate(pool.map(_chunk, jobs), 1):
            parts.append(part)
            if done % 200 == 0:
                log(f"  {done * chunk:,} triples  {time.perf_counter() - began:,.0f}s")
    stats = np.concatenate(parts)
    log(f"done in {time.perf_counter() - began:,.0f}s")
    return _expand(triples, stats, samples)


def _expand(triples: np.ndarray, stats: np.ndarray, samples: int) -> Tables:
    """Write each triple's numbers into all 6 seat orders; repeated classes get averaged."""
    eq3 = np.zeros((N, N, N))
    pw = np.zeros((N, N, N))
    hits = np.zeros((N, N, N))
    win = {(0, 1): stats[:, 3], (0, 2): stats[:, 4], (1, 2): stats[:, 5]}
    for x, y, z in itertools.permutations(range(3)):
        cell = (triples[:, x], triples[:, y], triples[:, z])
        np.add.at(eq3, cell, stats[:, x])
        np.add.at(pw, cell, win[(x, y)] if x < y else 1.0 - win[(y, x)])
        np.add.at(hits, cell, 1.0)
    possible = hits > 0
    # Impossible triples (AA, AA, AKo) get a plain split. Heads-up they carry no weight;
    # multiway (opponents dealt independently) they carry a tiny prior weight, still zero-sum.
    eq3 = np.where(possible, eq3 / np.maximum(hits, 1), 1 / 3)
    pw = np.where(possible, pw / np.maximum(hits, 1), 0.5)
    return Tables(np.empty(0), eq3.astype(np.float32), pw.astype(np.float32), possible, samples)


@functools.lru_cache(maxsize=1)
def two_way() -> np.ndarray:
    """e2, read from tmp/ or built from the exact combo cache (about 2 seconds)."""
    E2_FILE.parent.mkdir(exist_ok=True)
    if not E2_FILE.exists():
        np.savez_compressed(E2_FILE, e2=build_e2())
    with np.load(E2_FILE) as saved:
        return saved["e2"]


@functools.lru_cache(maxsize=1)
def three_way() -> Tables:
    """eq3 and pw, read from tmp/ or built by Monte Carlo (minutes, all cores)."""
    if not E3_FILE.exists():
        built = build_three_way()
        np.savez_compressed(E3_FILE, eq3=built.eq3, pw=built.pw, possible=built.possible,
                            samples=built.samples)
    with np.load(E3_FILE) as saved:
        return Tables(two_way(), saved["eq3"], saved["pw"], saved["possible"], int(saved["samples"]))


def load() -> Tables:
    return three_way()


if __name__ == "__main__":
    load()
