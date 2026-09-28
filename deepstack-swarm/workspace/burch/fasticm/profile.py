"""Where the fast audit's keys and its time actually go, per n."""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path("/Users/nuttakit/project/poker-harness")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "open3bet"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "johanson"))

from pushfold import icm  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

import fasticm3  # noqa: E402
import floor3  # noqa: E402
import pricer3  # noqa: E402
import seqbr  # noqa: E402
import seqbr3  # noqa: E402

for n in (3, 4, 6, 9):
    spot = Spot(stacks=(15.0,) * n)
    tree = floor3.build(spot, tier1=True)
    payouts = icm.Payouts(prizes=(50.0, 30.0, 20.0), field=(15.0,) * max(0, 4 - n))
    game = seqbr3.from_floor3(tree)
    fp = fasticm3.plan(tree, payouts)
    k = fp.keys
    hero = k[k[:, 1] == -1]
    u_yx = {tuple(t) for t in k[:, [0, 2, 3]].tolist()}
    u_hero = {tuple(t) for t in hero[:, [0, 2, 3]].tolist()}
    cols = fp.columns(np.full((len(tree.nodes), 169, tree.max_actions),
                             1.0 / tree.max_actions))

    t0 = time.perf_counter(); fasticm3._c_keys(k, cols); t_keys = time.perf_counter() - t0
    t0 = time.perf_counter(); fp.all_terminal_values(cols); t_all = time.perf_counter() - t0
    sigma = np.zeros((len(tree.nodes), 169, tree.max_actions))
    for nd in tree.nodes:
        sigma[nd.index, :, :len(nd.actions)] = 1.0 / len(nd.actions)
    paths = seqbr.path_columns(game, sigma)
    t0 = time.perf_counter(); seqbr._worth(game, payouts); t_worth = time.perf_counter() - t0
    print(f"n={n}: keys={len(k)} ({len(hero)} HERO) distinct (l,y,x)={len(u_yx)} "
          f"(HERO subset {len(u_hero)}) | _c_keys {t_keys:.3f}s all_values {t_all:.3f}s "
          f"_worth(cached) {t_worth:.3f}s path_columns {time.perf_counter() - t0:.3f}s")
