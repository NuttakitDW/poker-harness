"""Is a paired epsilon tighter than the self-play one? Measured, not assumed.

Two solutions of the same spot at different stop targets are two different charts. Simulated
on the same deals with the same action draws (`uniforms`), the per-hand difference is a paired
comparison; its SD, next to the SD of either chart alone, says whether pairing would move the
lifetime threshold.

Result (6h 10bb, bb-ante 1.0, bubble 46 left of 300): chart dTV 8.58% between target 0.003 and
0.0005, sigma 2.66-3.00, paired SD of the difference 3.23-3.65, ratio 1.21. Pairing is NOT
tighter here -- common random numbers remove the card variance, but the charts disagree on
enough hands that the difference is more variable than either result. So `lifetime_eps.py`
keeps the self-play sigma, which is what the Cepheus criterion defines.
"""
from __future__ import annotations

import numpy as np

from pushfold import coach, hands
from pushfold.spot import Spot

from lifetime_eps import LIFETIME, Z, bubble, prize_ladder, simulate, uniforms


def main() -> None:
    _, p300, _ = prize_ladder("mtt_300_players.json")
    P = bubble(dict(prizes=p300, players_left=46, avg_bb=20.0, table=(10.0,) * 6))
    spot = Spot((10.0,) * 6, ante=1.0, ante_mode="bb")
    runs = {t: coach.solve(spot, method="cfr+", target=t, check_every=25, max_iters=20_000,
                           payouts=P) for t in (0.003, 0.0005)}
    a, b = runs[0.003], runs[0.0005]
    dtv = float((hands.PRIOR[None, :] * np.abs(a.strategy[:, :, 1] - b.strategy[:, :, 1])
                 ).sum(axis=1).max())
    n, hands_n = 6, 200_000
    u = uniforms(hands_n, n, 20260927)
    net_a = simulate(spot, a.tree, {s: a.strategy for s in range(n)}, hands_n, 20260927, P, u=u)
    net_b = simulate(spot, b.tree, {s: b.strategy for s in range(n)}, hands_n, 20260927, P, u=u)
    diff = net_a - net_b
    print(f"chart dTV {dtv * 100:.2f}%")
    print(f"  sigma, chart A     {np.round(net_a.std(axis=0), 4)}")
    print(f"  sigma, chart B     {np.round(net_b.std(axis=0), 4)}")
    print(f"  paired sd of diff  {np.round(diff.std(axis=0), 4)}")
    print(f"  ratio              {np.round(diff.std(axis=0) / net_a.std(axis=0), 4)}")
    print(f"  eps unpaired {Z * net_a.std(axis=0).max() / np.sqrt(LIFETIME):.6f}, "
          f"eps paired {Z * np.abs(diff).std(axis=0).max() / np.sqrt(LIFETIME):.6f}")


if __name__ == "__main__":
    main()
