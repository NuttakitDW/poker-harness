"""Build oddsmaker's 3-way tables under a chosen base seed, writing to a workspace npz.

Does not touch tmp/. `pushfold.oddsmaker.SEED` is a module global read at call time by
`build_three_way` (per-chunk seeds are `SEED + chunk_index`), so setting it here changes the
Monte Carlo draws without editing any file.

Baseline used by production: SEED = 20260924, whose chunk seeds span 20260924 .. 21079404.
Bases here are 10^7 apart so the per-chunk seed ranges do not overlap the baseline at all.

    .venv/bin/python deepstack-swarm/workspace/burch/seeds/build_tables.py <base_seed> <out.npz>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from pushfold import oddsmaker  # noqa: E402


def build(base_seed: int, out: Path, samples: int = 2000) -> None:
    oddsmaker.SEED = base_seed
    assert oddsmaker.SEED + 818480 < base_seed + 10**7
    t0 = time.perf_counter()
    tab = oddsmaker.build_three_way(samples=samples, log=lambda m: print(m, flush=True))
    np.savez_compressed(out, eq3=tab.eq3, pw=tab.pw, possible=tab.possible,
                        samples=tab.samples, base_seed=np.int64(base_seed))
    print(f"wrote {out} in {time.perf_counter() - t0:,.0f}s", flush=True)


if __name__ == "__main__":
    seed = int(sys.argv[1])
    dest = Path(sys.argv[2])
    dest.parent.mkdir(parents=True, exist_ok=True)
    build(seed, dest)
