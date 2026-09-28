"""Check mc_values against exact3_values at n=3 (independent sampling path)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, seqbr, cardbr
from pushfold import floor, icm
from pushfold.spot import Spot

rng=np.random.default_rng(11)
for label, spot, pay in [("3max chip", Spot(stacks=(10.,)*3), None),
                         ("3max ICM", Spot(stacks=(10.,)*3), icm.Payouts(prizes=(50.,30.,20.), field=(10.,)))]:
    tree=floor.build(spot); game=seqbr.from_floor(tree)
    r=rng.random((len(tree.nodes),169,1)); sigma=np.concatenate([1-r,r],axis=2)
    jt=cardbr.exact3_values(game,sigma,pay,weight="joint")
    U,cnt=cardbr.mc_values(game,sigma,pay,samples=400_000,seed=7)
    d=np.abs(U-jt)
    se=np.sqrt(((d**2).mean()))/np.sqrt(1)   # crude
    print(f"{label}: |mc-exact3| max {d.max():.4f}  rms {np.sqrt((d**2).mean()):.5f}  "
          f"counts min {cnt.min():.0f}")
