"""Prize structures and tournament stages, for when the real payouts are not read out.

mtt(): a generic big-field curve, not any one site's. Everyone paid gets the min cash
(1.5 buy-ins); the rest of the pool goes by (place + 1)^-1.5, shifted so the last place paid
gets exactly the min cash. At 1000 entrants, 150 paid: 1st ~ 20% of the pool, 9th ~ 1.9%,
close to common online structures. Three places or fewer use the usual sit-and-go splits.

Stage: how far a tournament has gone. Stage.bubble() puts it a few players above the money. With `left` players still in, only places 1..left are
still open; everyone away from this table is one crowd sharing a stack (see icm.py).
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from pushfold import icm

MIN_CASH = 1.5          # buy-ins
DECAY = 1.5
PAID_SHARE = 0.15       # share of the field paid
BUBBLE_MARGIN = 0.03    # on the bubble: places paid plus 3% (at least one more player)
DEFAULT_ENTRANTS = 1000
SIT_AND_GO = {1: (1.0,), 2: (0.65, 0.35), 3: (0.5, 0.3, 0.2)}


def _paid(entrants: int, paid_share: float, given: tuple[float, ...]) -> int:
    return len(given) if given else max(1, round(entrants * paid_share))


def mtt(entrants: int, paid: int) -> tuple[float, ...]:
    """Prizes for 1st..paid in buy-ins; they add up to `entrants` (the whole pool)."""
    if not 1 <= paid <= entrants:
        raise icm.PayoutError(f"need 1 <= places paid <= entrants, got {paid} paid of {entrants}")
    if paid in SIT_AND_GO:
        return tuple(round(entrants * share, 9) for share in SIT_AND_GO[paid])
    floor = min(MIN_CASH, 0.5 * entrants / paid)
    weights = np.arange(2, paid + 2, dtype=float) ** -DECAY - (paid + 1.0) ** -DECAY
    prizes = floor + (entrants - floor * paid) * weights / weights.sum()
    return tuple(float(p) for p in prizes)


@dataclasses.dataclass(frozen=True)
class Stage:
    entrants: int
    left: int
    paid_share: float = PAID_SHARE
    given: tuple[float, ...] = ()   # the real payouts, 1st..last paid, if read out

    def __post_init__(self) -> None:
        if not 1 <= self.left <= self.entrants:
            raise icm.PayoutError(f"need 1 <= players left <= entrants, got {self.left} of {self.entrants}")
        if not 0 < self.paid_share <= 1:
            raise icm.PayoutError(f"share paid must be above 0% and at most 100%, got {self.paid_share:.0%}")
        if self.paid > self.entrants:
            raise icm.PayoutError(f"{self.paid} places paid but only {self.entrants} entrants")

    @classmethod
    def bubble(cls, entrants: int, paid_share: float = PAID_SHARE, given: tuple[float, ...] = ()) -> Stage:
        paid = _paid(entrants, paid_share, given)
        left = min(entrants, paid + max(1, math.ceil(paid * BUBBLE_MARGIN)))
        return cls(entrants, left, paid_share, tuple(given))

    @property
    def paid(self) -> int:
        return _paid(self.entrants, self.paid_share, self.given)

    @property
    def in_money(self) -> bool:
        return self.left <= self.paid

    def prizes(self) -> tuple[float, ...]:
        """Places still open: 1st down to min(left, paid)."""
        return (self.given or mtt(self.entrants, self.paid))[:self.left]

    def payouts(self, table: int, crowd_stack: float) -> icm.Payouts:
        if self.left < table:
            raise icm.PayoutError(f"only {self.left} players left but {table} seated at this table")
        return icm.Payouts(self.prizes(), crowd=self.left - table, crowd_stack=crowd_stack)
