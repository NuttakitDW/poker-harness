"""Immutable preflop filter over the legacy six-handed PLO state."""

from __future__ import annotations

import dataclasses

from plo_icm.game import Action, PLOState


@dataclasses.dataclass(frozen=True)
class PreflopState:
    """PLO state with pot-only raises, a two-raise cap, and check-down postflop."""

    base: PLOState
    raises: int = 0
    max_raises: int = 2

    @classmethod
    def new(
        cls,
        stack_bb: float = 100.0,
        *,
        small_blind_bb: float = 0.5,
        big_blind_bb: float = 1.0,
        max_raises: int = 2,
    ) -> PreflopState:
        base = PLOState.new(
            (stack_bb,) * 6,
            sb=small_blind_bb,
            bb=big_blind_bb,
            ante=0.0,
            ante_mode="individual",
            opening_raise_mode="pot_only",
        )
        return cls(base=base, max_raises=max_raises)

    @property
    def actor(self) -> int | None:
        return None if self.terminal else self.base.actor

    @property
    def terminal(self) -> bool:
        return self.base.terminal or self.base.street > 0

    @property
    def street(self) -> int:
        return self.base.street

    @property
    def history(self) -> tuple[str, ...]:
        return self.base.history

    def legal_actions(self) -> tuple[Action, ...]:
        if self.terminal:
            return ()
        legal = self.base.legal_actions()
        if self.raises >= self.max_raises:
            legal = tuple(action for action in legal if action != Action.POT)
        return legal

    def action_amount(self, action: Action) -> float:
        if action not in self.legal_actions():
            raise ValueError(
                f"illegal {action.value}; legal: {[item.value for item in self.legal_actions()]}"
            )
        return self.base.action_amount(action)

    def apply(self, action: Action) -> PreflopState:
        if action not in self.legal_actions():
            raise ValueError(
                f"illegal {action.value}; legal: {[item.value for item in self.legal_actions()]}"
            )
        is_raise = (
            action == Action.POT
            and self.base.actor is not None
            and self.base.street_put[self.base.actor]
            + self.base.action_amount(action)
            > self.base.current_bet
        )
        return dataclasses.replace(
            self,
            base=self.base.apply(action),
            raises=self.raises + int(is_raise),
        )
