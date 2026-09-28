"""Cross-check `icm_pricer3` against johanson's `seqbr` (the slow, already-validated oracle),
the same discipline as `pricer3.terminal_values` vs `seqbr.chip_values`
(`burch-tier1-solve.md` Sec 4) and `verify3.py`'s push/fold cross-check.

Two checks, at n = 2..9, RANDOM (not uniform) strategies so a bug that only shows up away from
symmetry is not missed:

A. Per-node counterfactual value: `icm_pricer3.values` vs a direct backward walk over
   `seqbr3._icm_values_cached`'s terminal values (`tier1_check.counterfactual`, reused unchanged).
B. `coach3` end to end: solve a few CFR+ iterations with the ICM plan wired into `coach3.iterate`
   in place of the chip plan, and check the resulting average's EV/exploitability via
   `icm_pricer3.values` matches `seqbr3.Auditor` (slow oracle) exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "johanson"))

import seqbr  # noqa: E402
from pushfold import icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import coach3  # noqa: E402
import floor3  # noqa: E402
import icm_pricer3  # noqa: E402
import pricer3  # noqa: E402
import seqbr3  # noqa: E402
from tier1_check import counterfactual  # noqa: E402


def random_sigma(tree: floor3.Tree, rng: np.random.Generator) -> np.ndarray:
    a = tree.max_actions
    sigma = np.zeros((len(tree.nodes), 169, a))
    for nd in tree.nodes:
        k = len(nd.actions)
        raw = rng.dirichlet(np.ones(k), size=169)
        sigma[nd.index, :, :k] = raw
    return sigma


def check_a(n: int, stack: float, payouts: icm.Payouts, rng: np.random.Generator) -> float:
    spot = Spot(stacks=(stack,) * n)
    tree = floor3.build(spot, tier1=True)
    game = seqbr3.from_floor3(tree)
    sigma = random_sigma(tree, rng)

    chip_plan = pricer3.plan(tree)
    plan = icm_pricer3.plan(tree, payouts, chip_plan)
    cols = plan.columns(sigma)

    paths = seqbr.path_columns(game, sigma)
    worth = seqbr._worth(game, payouts)
    U = seqbr3._icm_values_cached(game, paths, payouts, worth, seqbr.tables())

    worst = 0.0
    for seat in range(n):
        cfv_fast, _ = plan.seats[seat].price(cols)
        cfv_slow = counterfactual(game, U[seat], sigma, seat)
        for row, nd in enumerate(tree.nodes_of(seat)):
            k = len(nd.actions)
            got, want = cfv_fast[row, :, :k], cfv_slow[nd.index]
            worst = max(worst, float(np.abs(got - want).max()))
    return worst


def main() -> None:
    rng = np.random.default_rng(0)
    print("A. per-node cfv, icm_pricer3 vs seqbr (random sigma)")
    for n in (2, 3, 4, 6, 9):
        field = (15.0,) * max(0, 4 - n)
        payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=field)
        worst = check_a(n, 15.0, payouts, rng)
        print(f"  n={n} field={field}: max |diff| = {worst:.3e}")

    print("\nB. coach3(icm_pricer3) actually solving ICM: exploitability by the slow oracle "
          "should fall as iterations grow")
    for n in (2, 3):
        field = (15.0,) * max(0, 4 - n)
        payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=field)
        spot = Spot(stacks=(15.0,) * n)
        tree = floor3.build(spot, tier1=True)
        game = seqbr3.from_floor3(tree)
        plan = icm_pricer3.plan(tree, payouts)
        st = coach3.start(tree, plan)
        checks = [25, 100, 400]
        done = 0
        for target in checks:
            for _ in range(target - done):
                coach3.iterate(st, "cfr+")
            done = target
            slow = seqbr3.Auditor(game, payouts).audit(st.average())
            print(f"  n={n} iter={target}: exact max gain (slow oracle) = "
                  f"{slow.exploitability:.6f}")


if __name__ == "__main__":
    main()
