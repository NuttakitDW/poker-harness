"""Fixed-n simultaneous Hoeffding inference and generic rejection sampling."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class HoeffdingBound:
    one_sided_radius_x: float
    lower_true_deviation_gain_bb: float
    upper_conservative_surrogate_bb: float
    two_sided_surrogate_radius_x: float
    two_sided_surrogate_lower_bb: float
    two_sided_surrogate_upper_bb: float
    familywise_alpha: float
    simultaneous_cells: int
    interpretation: str


def hoeffding_bound(
    *, mean_x: float, accepted: int, cells: int, alpha: float = 0.05
) -> HoeffdingBound:
    """Return one-sided Bonferroni-Hoeffding bounds transformed to delta BB."""
    if not 0.0 <= mean_x <= 1.0:
        raise ValueError("mean_x must be in [0, 1]")
    if accepted <= 0 or cells <= 0:
        raise ValueError("accepted and cells must be positive")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    one_sided_radius = math.sqrt(math.log(cells / alpha) / (2 * accepted))
    two_sided_radius = math.sqrt(math.log(2 * cells / alpha) / (2 * accepted))
    return HoeffdingBound(
        one_sided_radius_x=one_sided_radius,
        lower_true_deviation_gain_bb=2 * (mean_x - one_sided_radius) - 0.5,
        upper_conservative_surrogate_bb=2 * (mean_x + one_sided_radius) - 0.5,
        two_sided_surrogate_radius_x=two_sided_radius,
        two_sided_surrogate_lower_bb=2 * (mean_x - two_sided_radius) - 0.5,
        two_sided_surrogate_upper_bb=2 * (mean_x + two_sided_radius) - 0.5,
        familywise_alpha=alpha,
        simultaneous_cells=cells,
        interpretation=(
            "The one-sided lower endpoint lower-bounds true deviation gain. "
            "The one-sided upper endpoint and log(2K/alpha) two-sided interval "
            "describe only the conservative surrogate and are not an upper bound on true gain."
        ),
    )


@dataclass(frozen=True)
class SurrogateHoeffdingBound:
    one_sided_radius_bb: float
    lower_true_deviation_gain_bb: float
    upper_conservative_surrogate_bb: float
    two_sided_surrogate_radius_bb: float
    two_sided_surrogate_lower_bb: float
    two_sided_surrogate_upper_bb: float
    familywise_alpha: float
    simultaneous_cells: int
    sample_range_bb: tuple[float, float]
    interpretation: str


def surrogate_hoeffding_bound(
    *,
    mean_surrogate_bb: float,
    samples: int,
    cells: int,
    alpha: float = 0.05,
    sample_lower_bb: float = -0.5,
    sample_upper_bb: float = 1.5,
) -> SurrogateHoeffdingBound:
    """Simultaneous bounds for a bounded conservative gain surrogate."""
    if samples <= 0 or cells <= 0:
        raise ValueError("samples and cells must be positive")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    if sample_lower_bb >= sample_upper_bb:
        raise ValueError("sample range must be increasing")
    if not sample_lower_bb <= mean_surrogate_bb <= sample_upper_bb:
        raise ValueError("mean surrogate lies outside its sample range")
    width = sample_upper_bb - sample_lower_bb
    one_sided = width * math.sqrt(math.log(cells / alpha) / (2 * samples))
    two_sided = width * math.sqrt(math.log(2 * cells / alpha) / (2 * samples))
    return SurrogateHoeffdingBound(
        one_sided_radius_bb=one_sided,
        lower_true_deviation_gain_bb=mean_surrogate_bb - one_sided,
        upper_conservative_surrogate_bb=mean_surrogate_bb + one_sided,
        two_sided_surrogate_radius_bb=two_sided,
        two_sided_surrogate_lower_bb=mean_surrogate_bb - two_sided,
        two_sided_surrogate_upper_bb=mean_surrogate_bb + two_sided,
        familywise_alpha=alpha,
        simultaneous_cells=cells,
        sample_range_bb=(sample_lower_bb, sample_upper_bb),
        interpretation=(
            "The one-sided lower endpoint lower-bounds true deviation gain. "
            "The upper endpoint and the log(2K/alpha) two-sided interval apply only "
            "to the conservative surrogate, not to true gain."
        ),
    )


def rejection_sample[T](
    rng: random.Random,
    *,
    draw: Callable[[random.Random], T],
    accept: Callable[[T], bool],
    target: int,
) -> tuple[list[T], int]:
    """Draw independently with replacement and retain draws satisfying an event."""
    if target <= 0:
        raise ValueError("target must be positive")
    accepted: list[T] = []
    draws = 0
    while len(accepted) < target:
        value = draw(rng)
        draws += 1
        if accept(value):
            accepted.append(value)
    return accepted, draws
