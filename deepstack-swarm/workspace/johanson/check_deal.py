"""Is the exact class joint right, and does MC dealing agree with it?

Run: .venv/bin/python deepstack-swarm/workspace/johanson/check_deal.py
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import deal
from pushfold import hands

t = time.perf_counter()
J = deal.joint2(verbose=True)
print(f"joint2 built in {time.perf_counter()-t:.0f}s  shape={J.shape}  rows sum to "
      f"[{J.sum(axis=(1,2)).min():.12f}, {J.sum(axis=(1,2)).max():.12f}]")

marg_g = J.sum(axis=2)          # P(opp1 class g | hero h)
marg_k = J.sum(axis=1)
print(f"max |marginal - hands.M|  opp1 {np.abs(marg_g - hands.M).max():.3e}  "
      f"opp2 {np.abs(marg_k - hands.M).max():.3e}")

# MC check: deal two opponents from the remaining deck, compare the class pair histogram.
rng = np.random.default_rng(7)
S = 2_000_000
hero = rng.integers(0, 169, size=S)
opp = deal.opponent_sets(hero, 3, S, rng)
# compare for a few hero classes
for h in (hands.index("AA"), hands.index("AKs"), hands.index("72o"), hands.index("QQ")):
    sel = hero == h
    est = np.zeros((169, 169))
    np.add.at(est, (opp[sel, 0], opp[sel, 1]), 1.0)
    est /= sel.sum()
    print(f"{hands.CLASSES[h]:>4}: N={sel.sum():>7,}  max|MC - exact| {np.abs(est - J[h]).max():.2e}  "
          f"(3 sigma ~ {3*np.sqrt(1/max(sel.sum(),1)):.1e})")
    # marginal check at combos: how much of the deck does each opponent use
print("MC marginal vs M:", np.abs(np.array([np.bincount(opp[hero==h,0], minlength=169)/max((hero==h).sum(),1)
      for h in range(0,169,17)]) - hands.M[0::17]).max())
