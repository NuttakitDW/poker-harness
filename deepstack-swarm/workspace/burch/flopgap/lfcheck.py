"""behind_cap=1: unchanged at equal stacks, zero FLOP terminals at unequal stacks."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm/workspace/burch/open3bet"))
from pushfold.spot import Spot
import floor3

SPOTS = {
    "15x6": (15.0,) * 6,
    "15x9": (15.0,) * 9,
    "15x3": (15.0,) * 3,
    "15x2": (15.0,) * 2,
    "6max-uneven": (4.0, 8.0, 15.0, 20.0, 30.0, 15.0),
    "2,15..": (2.0, 15.0, 15.0, 15.0, 15.0, 15.0),
    "ladder5-30": (5.0, 10.0, 15.0, 20.0, 25.0, 30.0),
    "3max-uneven": (5.0, 15.0, 30.0),
    "3max-2-15-15": (2.0, 15.0, 15.0),
}
for name, stacks in SPOTS.items():
    spot = Spot(stacks=stacks)
    a = floor3.build(spot, tier1=True)
    b = floor3.build(spot, tier1=True, behind_cap=1)
    same = (a.counts() == b.counts() and len(a.nodes) == len(b.nodes)
            and len(a.terminals) == len(b.terminals))
    print(f"{name:>14} n={spot.n} as-is {a.counts()} | lf {b.counts()} "
          f"| nodes {len(a.nodes)}->{len(b.nodes)} terms {len(a.terminals)}->{len(b.terminals)} "
          f"| identical={same}")
