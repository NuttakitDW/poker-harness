"""Scenario builder for the first Tier 1 ICM chart.

A scenario is a spot geometry plus a payout setting. Geometry follows the swarm's Tier 1
conventions (burch-tier1-solve.md): preflop only, n seats, equal stacks (bb), sb 0.5 / bb 1,
no ante, fee 0, cap 3. Payouts come from deepstack-swarm/assets/.

Stage is encoded the only way ICM can see it: how many players are left and how many places
are paid, with the rest of the field carried as a crowd that all share one stack
(pushfold/icm.py:22-27). That is bard's point (bard-scenario-grid.md): field size and stack
configuration are their own axes, not a function of one another.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm" / "workspace" / "burch" / "open3bet"))

from pushfold import icm  # noqa: E402

ASSETS = ROOT / "deepstack-swarm" / "assets"

SETTINGS = {
    "small": ASSETS / "mtt_300_players.json",     # 300 runners, 45 paid
    "big": ASSETS / "mtt_1500_payout.json",       # 1500 runners, 225 paid
}


def prizes(setting: str) -> tuple[float, ...]:
    d = json.loads(SETTINGS[setting].read_text())
    pr = d["structures"][0]["prizes"]
    return tuple(pr[k] for k in sorted(pr, key=int))


def payouts(setting: str, table: int, left: int, stack: float) -> icm.Payouts:
    """ICM payouts for `table` seats at `stack` bb each, `left` players still in, all equal.

    The players not at the table become a crowd, each holding `stack` bb, which is exact
    Harville (pushfold/icm.py docstring) and keeps the field size in the model.
    """
    crowd = left - table
    if crowd < 0:
        raise ValueError(f"{left} players left cannot fill a {table}-seat table")
    return icm.Payouts(prizes=prizes(setting), field=(), crowd=crowd, crowd_stack=stack)


def stages(setting: str) -> list[int]:
    """(label, players left) on the stage axis.

    The bubble is `paid + 1` -- one player off the money -- not `paid`, at which point every
    remaining player is already paid and there is no bubble factor at all. `deep` is well past
    the money, where ICM flattens out toward chip EV.
    """
    paid = len(prizes(setting))
    return [("bubble", paid + 1), ("past", round(paid * 2.0)), ("deep", round(paid * 6.0))]
