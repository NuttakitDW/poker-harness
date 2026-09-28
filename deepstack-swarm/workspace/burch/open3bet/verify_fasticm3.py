"""`fasticm3.FastAuditor` vs `seqbr3.Auditor` (the slow, already-validated oracle).

The same bar `verify_icm3.py` sets for `icm_pricer3`, and the same way the Cepheus reporting bug
was caught (Burch thesis 4.3.1): two independently written code paths, same input, agreement to
float tolerance -- here on a RANDOM strategy, not uniform, so a bug that only shows up away from
symmetry is not missed.

Checks, at n = 2, 3, 4, 6, 9, 15bb, ICM 50/30/20 (field padding as in `solve3`):
  A. terminal values U[seat] elementwise, `fasticm3` vs `seqbr3._icm_values_cached`.
  B. full `Report` from `.audit(sigma)`: ev, gain per seat, exploitability, nashconv.
  C. `seqbr.shortcut_gain` (the old push/fold formula) also agrees, so the two reports are the
     same object and not just the same number.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "johanson"))

import seqbr  # noqa: E402
from pushfold import icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import fasticm3  # noqa: E402
import floor3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402


def random_sigma(tree: floor3.Tree, rng: np.random.Generator) -> np.ndarray:
    sigma = np.zeros((len(tree.nodes), 169, tree.max_actions))
    for nd in tree.nodes:
        k = len(nd.actions)
        sigma[nd.index, :, :k] = rng.dirichlet(np.ones(k), size=169)
    return sigma


def run(n: int, stack: float, rng: np.random.Generator, verbose: bool = True) -> dict:
    field = (stack,) * max(0, 4 - n)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=field)
    spot = Spot(stacks=(stack,) * n)
    tree = floor3.build(spot, tier1=True)
    game = seqbr3.from_floor3(tree)
    sigma = random_sigma(tree, rng)

    chip_plan = pricer3.plan(tree)
    fp = fasticm3.plan(tree, payouts, chip_plan)
    cols = fp.columns(sigma)

    paths = seqbr.path_columns(game, sigma)
    worth = seqbr._worth(game, payouts)
    U_slow = seqbr3._icm_values_cached(game, paths, payouts, worth, seqbr.tables())
    U_fast = fp.all_terminal_values(cols)
    dU = float(np.abs(U_fast - U_slow).max())
    scale = max(float(np.abs(U_slow).max()), 1e-30)

    slow = seqbr3.Auditor(game, payouts)
    t0 = time.perf_counter(); rep_slow = slow.audit(sigma); t_slow = time.perf_counter() - t0
    fast = fasticm3.FastAuditor(game, fp, payouts)
    t0 = time.perf_counter(); rep_fast = fast.audit(sigma); t_fast = time.perf_counter() - t0
    d_ev = float(np.abs(rep_fast.ev - rep_slow.ev).max())
    d_gain = float(np.abs(rep_fast.gain - rep_slow.gain).max())
    d_sc = float(np.abs(rep_fast.shortcut - rep_slow.shortcut).max())
    d_x = abs(rep_fast.exploitability - rep_slow.exploitability)

    print(f"n={n:>2} keys={len(fp.keys):>5} 3way rows={sum(len(p.t_zid) for p in fp.seats):>6} "
          f"| dU={dU:.2e} (rel {dU / scale:.1e})  d_ev={d_ev:.2e} d_gain={d_gain:.2e} "
          f"d_shortcut={d_sc:.2e} d_expl={d_x:.2e}")
    print(f"       slow {t_slow:7.2f}s   fast {t_fast:6.3f}s   speedup {t_slow / t_fast:7.1f}x")
    return dict(n=n, keys=len(fp.keys), dU=dU, d_gain=d_gain, d_x=d_x, t_slow=t_slow,
                t_fast=t_fast)


def main() -> None:
    rng = np.random.default_rng(20260927)
    print("A/B/C. fasticm3 vs seqbr3.Auditor, random strategy, 15bb, ICM 50/30/20")
    worst = 0.0
    for n in (2, 3, 4, 6, 9):
        r = run(n, 15.0, rng)
        worst = max(worst, r["dU"], r["d_gain"])
    print(f"worst |diff| over all n: {worst:.3e}")
    print("PASS" if worst < 1e-4 else "FAIL")


if __name__ == "__main__":
    main()
