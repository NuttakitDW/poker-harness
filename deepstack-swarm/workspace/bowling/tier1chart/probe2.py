import sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "burch" / "open3bet"))
import scenarios as S
from pushfold.spot import Spot
import floor3, coach3, icm_pricer3, pricer3, seqbr3
for n in (3, 6, 9):
    tree = floor3.build(Spot(stacks=(15.0,) * n), tier1=True)
    pay = S.payouts("small", n, 45, 15.0)
    plan = icm_pricer3.plan(tree, pay)
    st = coach3.start(tree, plan)
    game = seqbr3.from_floor3(tree)
    aud = seqbr3.Auditor(game, pay)
    t0 = time.perf_counter(); [coach3.iterate(st, "cfr+") for _ in range(100)]; ti = (time.perf_counter()-t0)/100
    t0 = time.perf_counter(); r = aud.audit(st.average()); ta = time.perf_counter()-t0
    t0 = time.perf_counter(); coach3.iterate(st, "cfr+"); ta2 = time.perf_counter()-t0; _ = r
    print(f"n={n:>2} iter {ti*1000:7.2f} ms | audit {ta:6.2f} s = {ta/ti:6.0f} iterations | "
          f"=> to 0.0006 needs X iters + X/{100} audits", flush=True)
