"""Shape of the ICM audit problem: tree size, terminal mix, and where the 90s goes at n=9."""
import sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "open3bet"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "johanson"))

from pushfold import icm, hands
from pushfold.spot import Spot
import floor3, pricer3, icm_pricer3, seqbr3, seqbr

for n in (2, 3, 4, 6, 9):
    stack = 15.0
    spot = Spot(stacks=(stack,) * n)
    tree = floor3.build(spot, tier1=True)
    field = (stack,) * max(0, 4 - n)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=field)
    counts = tree.counts()
    alive3 = sum(1 for z in tree.terminals if len(z.live) == 3)
    alive2 = sum(1 for z in tree.terminals if len(z.live) == 2)
    alive1 = sum(1 for z in tree.terminals if len(z.live) == 1)
    chip_plan = pricer3.plan(tree)
    plan = icm_pricer3.plan(tree, payouts, chip_plan)
    print(f"n={n}: nodes={len(tree.nodes)} terminals={len(tree.terminals)} seqs={tree.sequences} "
          f"prods={len(chip_plan.prods)} counts={counts}")
    print(f"      alive1={alive1} alive2={alive2} alive3={alive3} maxactions={tree.max_actions} "
          f"depth_own={tree.depth_of_own_decisions()}")
    # group counts in the 3-way plan
    g = [len(p.group_target) for p in plan.seats]
    print(f"      icm plan 3-way groups per seat: {g}")
