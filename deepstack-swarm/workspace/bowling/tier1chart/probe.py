import sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
import scenarios as S
from pushfold.spot import Spot
import floor3, solve3
for n in (6, 9):
    tree = floor3.build(Spot(stacks=(15.0,) * n), tier1=True)
    pay = S.payouts("small", n, 45, 15.0)
    t0 = time.perf_counter()
    sol = solve3.solve_icm(tree, pay, 0.0006, "cfr+", check_every=200, max_iters=200)
    dt = time.perf_counter() - t0
    print(f"n={n} nodes={len(tree.nodes)} terms={len(tree.terminals)} "
          f"200 iters + 1 audit in {dt:.1f}s -> {dt/200*1000:.0f} ms/iter incl audit "
          f"(audit alone ~{dt - 200*(dt/200):.1f}s not separated)", flush=True)
