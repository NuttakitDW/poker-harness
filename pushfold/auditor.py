"""The Auditor: how much could any one seat gain by changing its strategy alone?

Each seat acts at most once, so its best response is simply the better action at each
of its nodes, hand by hand. Exploitability = the largest such gain, in bb per hand.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from pushfold import hands, pricer
from pushfold.floor import Tree


@dataclasses.dataclass(frozen=True)
class Report:
    ev: np.ndarray       # chip EV per seat, bb per hand
    gain: np.ndarray     # best-response gain per seat
    exploitability: float


def audit(tree: Tree, sigma: np.ndarray, plans: list[pricer.SeatPlan] | None = None) -> Report:
    plans = plans or pricer.plan(tree)
    cols = pricer.columns(sigma)
    ev, gain = [], []
    for p in plans:
        cfv, fixed = pricer.values(p, cols)
        mine = sigma[p.nodes]
        now = (mine * cfv).sum(axis=2)
        ev.append(hands.PRIOR @ (now.sum(axis=0) + fixed))
        gain.append(hands.PRIOR @ (cfv.max(axis=2) - now).sum(axis=0))
    gain = np.array(gain)
    return Report(np.array(ev), gain, float(gain.max()))
