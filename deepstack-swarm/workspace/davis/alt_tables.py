"""Build the 3-way equity tables a second time with different seeds.

Nothing in pushfold/ is touched: this only rebinds `oddsmaker.SEED` (read per chunk at call
time) and writes the result to the workspace. The point is a noise budget for `eq3`/`pw`:
two independent 2000-deal builds differ by 2 x the per-cell Monte Carlo noise, so the
difference between them measures the table noise directly, and re-solving one spot on the
alternate tables measures what that noise does to EV, exploitability and chart.
"""
from __future__ import annotations

import numpy as np

from pushfold import oddsmaker

OUT = "deepstack-swarm/workspace/davis/e3-alt.npz"

if __name__ == "__main__":
    oddsmaker.SEED = 1_000_003
    print(f"SEED={oddsmaker.SEED} samples={oddsmaker.SAMPLES}", flush=True)
    t = oddsmaker.build_three_way(samples=oddsmaker.SAMPLES, workers=None, chunk=256,
                                  log=lambda m: print(m, flush=True))
    np.savez_compressed(OUT, eq3=t.eq3, pw=t.pw, possible=t.possible, samples=t.samples)
    print("wrote", OUT, flush=True)
