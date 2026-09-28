"""What the real number is AT the stop rule the product actually uses (default target=0.01)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, seqbr, cardbr, inspect
from pushfold import coach, floor, icm
from pushfold.spot import Spot
print("coach.solve defaults:", inspect.signature(coach.solve))
for label, pay in [("chip", None), ("ICM", icm.Payouts(prizes=(50.,30.,20.), field=(10.,)))]:
    spot = Spot(stacks=(10.,)*3)
    for target in (0.01, 1e-4):
        res = coach.solve(spot, payouts=pay, target=target)
        game = seqbr.from_floor(floor.build(spot)); s = res.strategy
        rm = seqbr.audit(game, s, pay, U=cardbr.analytic_values(game, s, pay, kind="model"))
        rr = seqbr.audit(game, s, pay, U=cardbr.exact3_values(game, s, pay, weight="joint"))
        print(f"3max {label:<4} target={target:<7g} stopped at {res.iterations:>5} it  "
              f"model {rm.gain.max():.6f}  real {rr.gain.max():.6f}  ratio {rr.gain.max()/rm.gain.max():.2f}x")
