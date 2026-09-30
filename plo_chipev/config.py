"""Strict standalone configuration for the fixed PLO chip-EV tournament table."""

from __future__ import annotations

import dataclasses
import math
from typing import Any


class ConfigError(ValueError):
    """Raised when a chip-EV game configuration is invalid."""


@dataclasses.dataclass(frozen=True)
class Config:
    """Serializable configuration with fixed game semantics and bounded training."""

    variant: str = "PLO4-high"
    format: str = "tournament"
    players: int = 6
    stack_bb: float = 100.0
    small_blind_bb: float = 0.5
    big_blind_bb: float = 1.0
    ante_bb: float = 0.0
    rake: float = 0.0
    utility: str = "chip_ev"
    payouts_or_icm: bool = False
    postflop: str = "check_down"
    max_voluntary_raises: int = 2
    hand_abstraction: str = "features"
    seed: int = 1
    iterations: int = 1_000
    time_limit_seconds: float | None = None
    max_nodes: int = 1_000_000
    max_infosets: int = 250_000
    averaging_epsilon: float = 0.05

    def __post_init__(self) -> None:
        numeric = (
            "stack_bb",
            "small_blind_bb",
            "big_blind_bb",
            "ante_bb",
            "rake",
            "averaging_epsilon",
        )
        for name in numeric:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name} must be numeric")
        if self.time_limit_seconds is not None and (
            isinstance(self.time_limit_seconds, bool)
            or not isinstance(self.time_limit_seconds, (int, float))
        ):
            raise ConfigError("time_limit_seconds must be numeric or null")
        object.__setattr__(self, "stack_bb", float(self.stack_bb))
        object.__setattr__(self, "small_blind_bb", float(self.small_blind_bb))
        object.__setattr__(self, "big_blind_bb", float(self.big_blind_bb))
        object.__setattr__(self, "ante_bb", float(self.ante_bb))
        object.__setattr__(self, "rake", float(self.rake))
        object.__setattr__(self, "averaging_epsilon", float(self.averaging_epsilon))
        if self.time_limit_seconds is not None:
            object.__setattr__(self, "time_limit_seconds", float(self.time_limit_seconds))
        self.validate()

    def validate(self) -> None:
        fixed = (
            ("variant", self.variant, "PLO4-high"),
            ("format", self.format, "tournament"),
            ("players", self.players, 6),
            ("small_blind_bb", self.small_blind_bb, 0.5),
            ("big_blind_bb", self.big_blind_bb, 1.0),
            ("ante_bb", self.ante_bb, 0.0),
            ("rake", self.rake, 0.0),
            ("utility", self.utility, "chip_ev"),
            ("payouts_or_icm", self.payouts_or_icm, False),
            ("postflop", self.postflop, "check_down"),
            ("max_voluntary_raises", self.max_voluntary_raises, 2),
        )
        for name, actual, expected in fixed:
            if actual != expected:
                raise ConfigError(f"{name} must be {expected}")
        if self.stack_bb != 100:
            raise ConfigError("stack_bb must be 100")
        if self.hand_abstraction not in {"features", "exact"}:
            raise ConfigError("hand_abstraction must be features or exact")
        integer_fields = (
            ("seed", self.seed),
            ("iterations", self.iterations),
            ("max_nodes", self.max_nodes),
            ("max_infosets", self.max_infosets),
        )
        for name, value in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(f"{name} must be an integer")
        if self.iterations < 0:
            raise ConfigError("iterations must be nonnegative")
        if self.max_nodes <= 0 or self.max_infosets <= 0:
            raise ConfigError("max_nodes and max_infosets must be positive")
        if self.time_limit_seconds is not None and (
            not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0
        ):
            raise ConfigError("time_limit_seconds must be finite and positive")
        if not math.isfinite(self.averaging_epsilon) or not 0 < self.averaging_epsilon <= 1:
            raise ConfigError("averaging_epsilon must be in (0, 1]")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        if not isinstance(data, dict):
            raise ConfigError("configuration must be an object")
        known = {field.name for field in dataclasses.fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ConfigError("unknown configuration: " + ", ".join(unknown))
        try:
            return cls(**data)
        except TypeError as exc:
            raise ConfigError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
