"""Strict, serializable custom tournament configuration."""

from __future__ import annotations

import dataclasses
import math
from typing import Any


class ConfigError(ValueError):
    pass


SUNDAY_PAYOUTS = ((2087.06, 1547.88, 1148.27, 851.83, 631.92, 468.78, 347.75, 236.87)
                  + (191.94,) * 2 + (155.54,) * 2 + (126.04,) * 4 + (102.13,) * 6
                  + (82.76,) * 10 + (67.06,) * 16 + (54.34,) * 27)


@dataclasses.dataclass(frozen=True)
class Config:
    stacks: tuple[float, ...]
    payouts: tuple[float, ...]
    players_remaining: int
    outside_stack: float
    ante: float
    ante_mode: str
    sb: float = .5
    bb: float = 1.0
    iterations: int = 1000
    seed: int = 1
    time_limit: float | None = None
    max_nodes: int = 100_000
    max_infosets: int = 50_000
    averaging_epsilon: float = .05
    opening_raise_mode: str = "two_bb_only"

    def __post_init__(self) -> None:
        for name, values in (("stacks", self.stacks), ("payouts", self.payouts)):
            if not isinstance(values, (list, tuple)) or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                                            for x in values):
                raise ConfigError(f"{name} must contain only numeric values")
        for name in ("outside_stack", "ante", "sb", "bb", "averaging_epsilon"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name} must be numeric")
        if self.time_limit is not None and (isinstance(self.time_limit, bool)
                                            or not isinstance(self.time_limit, (int, float))):
            raise ConfigError("time_limit must be numeric or null")
        object.__setattr__(self, "stacks", tuple(float(x) for x in self.stacks))
        object.__setattr__(self, "payouts", tuple(float(x) for x in self.payouts))
        self.validate()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        if not isinstance(data, dict):
            raise ConfigError("configuration must be an object")
        required = {"stacks", "payouts", "players_remaining", "outside_stack", "ante", "ante_mode"}
        missing = sorted(required - data.keys())
        if missing:
            raise ConfigError("missing required configuration: " + ", ".join(missing))
        unknown = sorted(set(data) - {f.name for f in dataclasses.fields(cls)})
        if unknown:
            raise ConfigError("unknown configuration: " + ", ".join(unknown))
        try:
            cfg = cls(**data)
        except (TypeError, ValueError) as exc:
            raise ConfigError(str(exc)) from exc
        return cfg

    def validate(self) -> None:
        if self.opening_raise_mode not in ("two_bb_only", "pot_only", "both"):
            raise ConfigError("opening_raise_mode must be two_bb_only, pot_only, or both")
        if len(self.stacks) != 6:
            raise ConfigError("PLO 6-max requires exactly 6 table stacks")
        if any(not math.isfinite(s) or not 0 < s <= 10 for s in self.stacks):
            raise ConfigError("every starting stack must be finite and in (0, 10] bb")
        if not self.payouts or any(not math.isfinite(p) or p < 0 for p in self.payouts) or sum(self.payouts) <= 0:
            raise ConfigError("payouts must be a nonempty ordered list of finite values >= 0")
        if any(a < b for a, b in zip(self.payouts, self.payouts[1:])):
            raise ConfigError("payouts must be ordered from first place downward")
        integer_fields = (("players_remaining", self.players_remaining), ("iterations", self.iterations),
                          ("seed", self.seed), ("max_nodes", self.max_nodes),
                          ("max_infosets", self.max_infosets))
        if any(isinstance(x, bool) or not isinstance(x, int) for _, x in integer_fields):
            raise ConfigError("players_remaining, iterations, seed, max_nodes and max_infosets must be integers")
        if not 6 <= self.players_remaining or len(self.payouts) > self.players_remaining:
            raise ConfigError("players_remaining must cover the table and all paid places")
        if not math.isfinite(self.outside_stack) or self.outside_stack <= 0:
            raise ConfigError("outside_stack must be positive")
        if self.ante_mode not in ("individual", "bb"):
            raise ConfigError("ante_mode must be 'individual' or 'bb'")
        if not math.isfinite(self.ante) or self.ante < 0:
            raise ConfigError("ante must be finite and >= 0")
        if not all(math.isfinite(x) for x in (self.sb, self.bb)) or not (0 < self.sb <= self.bb):
            raise ConfigError("require finite 0 < sb <= bb")
        if self.bb != 1:
            raise ConfigError("stack units are big blinds, so bb must equal 1")
        if self.iterations < 0 or self.max_nodes <= 0 or self.max_infosets <= 0:
            raise ConfigError("iterations >= 0 and positive max_nodes/max_infosets required")
        if self.time_limit is not None and (not math.isfinite(self.time_limit) or self.time_limit <= 0):
            raise ConfigError("time_limit must be positive")
        if not 0 < self.averaging_epsilon <= 1:
            raise ConfigError("averaging_epsilon must be in (0, 1]")

    @property
    def outside_count(self) -> int:
        return self.players_remaining - 6

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def sunday_classic_mini(players_remaining: int = 76, stack: float = 10,
                        ante: float = .1, ante_mode: str = "individual", **limits: Any) -> Config:
    payouts = SUNDAY_PAYOUTS[:min(players_remaining, len(SUNDAY_PAYOUTS))]
    return Config.from_dict({"stacks": [stack] * 6, "payouts": payouts,
                             "players_remaining": players_remaining, "outside_stack": stack,
                             "ante": ante, "ante_mode": ante_mode, **limits})
