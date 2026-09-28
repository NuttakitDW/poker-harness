"""Independent Monte Carlo error of a single class triple, and the `orders()` clip bias.

`oddsmaker`'s 3-way tables are means over `samples` deals. Their error is not observable from one
seed, so this draws `batches` independent batches of `samples` deals for a random subset of
feasible triples and reports the spread across batches. It also counts how often
`pw[y,z,x] < eq3[y,z,x]`, which `oddsmaker.orders()` clips to zero -- `orders` is
clip(pw - eq3, 0), a nonlinear function of two noisy means, so its expectation is biased
near zero.

    .venv/bin/python deepstack-swarm/workspace/burch/seednoise/mc_se.py [triples] [batches] [samples]
"""

from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from pushfold import hands, oddsmaker  # noqa: E402

N = len(hands.CLASSES)


def main() -> None:
    ntri = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    batches = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    samples = int(sys.argv[3]) if len(sys.argv) > 3 else 2000

    feasible = np.array([t for t in itertools.combinations_with_replacement(range(N), 3)
                         if oddsmaker.rank_feasible(t)], dtype=np.int64)
    rng = np.random.default_rng(7)
    pick = feasible[rng.choice(len(feasible), size=ntri, replace=False)]

    t0 = time.perf_counter()
    stats = np.empty((batches, ntri, 6))
    for b in range(batches):
        stats[b] = oddsmaker._chunk((pick, samples, 10_000_000 + 7919 * b))
    print(f"{ntri} triples x {batches} batches x {samples} deals in {time.perf_counter()-t0:.0f}s",
          flush=True)

    # columns: 0,1,2 = eq3 of seat a,b,c ; 3,4,5 = pairwise win prob of (a,b),(a,c),(b,c)
    se = stats.std(axis=0, ddof=1) / np.sqrt(1.0)          # sd of one batch-mean, i.e. the SE
    print("\nper-triple Monte Carlo SE (one table entry, samples=%d)" % samples)
    for name, cols in (("eq3", [0, 1, 2]), ("pw", [3, 4, 5])):
        v = se[:, cols].ravel()
        print(f"  {name:4s} mean {v.mean():.5f}  median {np.median(v):.5f}  "
              f"p90 {np.quantile(v, .9):.5f}  max {v.max():.5f}")

    # orders[y,z,x] = clip(pw[y,z,x] - eq3[y,z,x], 0), the chance x is first and y is second.
    # The matched (pw, eq3) pairs in one triple's stats row are (3,0), (4,0), (5,1):
    # pw col 3 = P(0>1), col 4 = P(0>2), col 5 = P(1>2); eq3 col 0 = P(0 first), col 1 = P(1 first).
    pairs = [(3, 0), (4, 0), (5, 1)]
    raw = np.stack([stats[:, :, p] - stats[:, :, e] for p, e in pairs])     # (3, batches, ntri)
    print(f"\nraw (pw - eq3) across batches: mean {raw.mean():.5f}  sd {raw.std(axis=1).mean():.5f}")
    neg = float((raw < 0).mean())
    print(f"fraction of (pair, triple, batch) with pw < eq3, clipped to 0 by orders(): {neg:.4f}")

    bias = np.clip(raw, 0, None).mean(axis=1) - raw.mean(axis=1)            # (3, ntri)
    print(f"orders() clip bias per entry: mean {bias.mean():.6f}  p90 {np.quantile(bias, .9):.6f}  "
          f"max {bias.max():.6f}   (positive = inflated)")
    print(f"  of {3 * ntri} entries, {int((bias > 1e-4).sum())} have clip bias > 1e-4, "
          f"{int((bias > 1e-3).sum())} > 1e-3")

    # aggregate: the PRIOR-weighted 3-way sum a pricer actually multiplies in
    w = hands.PRIOR
    print(f"\nimplied SE of one row of sum_gk PRIOR[g]PRIOR[k]*eq3[h,g,k] "
          f"if entries were independent with the median SE above: "
          f"{np.median(se[:, [0,1,2]]) * float((w ** 2).sum()):.2e} bb")
    np.savez_compressed(Path(__file__).resolve().parent / "mc_se.npz", se=se, bias=bias,
                        neg=np.array(neg), samples=np.array(samples))


if __name__ == "__main__":
    main()
