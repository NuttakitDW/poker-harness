"""Static public tree with betting on every street (pot-sized, capped, all-in aware)."""

from __future__ import annotations

import dataclasses
import sys

import numpy as np

from plo_icm.game import EPS, Action, PLOState

ACTION_IDS = {"fold": 0, "check": 1, "call": 2, "pot": 3}
# Per-street information buckets: preflop tier-pure, flop/turn draw-aware, river strength.
STREET_BUCKETS = (780, 120, 120, 10)


@dataclasses.dataclass(frozen=True)
class FullTreeConfig:
    stack_bb: float = 20.0
    raise_caps: tuple[int, int, int, int] = (3, 2, 2, 2)

    def __post_init__(self) -> None:
        if not 1 <= self.stack_bb <= 200:
            raise ValueError("stack_bb must be between 1 and 200")
        if len(self.raise_caps) != 4 or any(cap < 0 for cap in self.raise_caps):
            raise ValueError("raise_caps needs four nonnegative street caps")


@dataclasses.dataclass(frozen=True)
class FullTree:
    config: FullTreeConfig
    actor: np.ndarray
    street: np.ndarray
    decision_index: np.ndarray
    children: np.ndarray
    action_ids: np.ndarray
    action_count: np.ndarray
    behind: np.ndarray
    sidepot_count: np.ndarray
    sidepot_amount: np.ndarray
    sidepot_eligible_mask: np.ndarray
    first_in_nodes: np.ndarray
    row_start: np.ndarray  # decision -> first row of its (bucket, action) table
    rows: int

    @property
    def decision_count(self) -> int:
        return int(self.row_start.size)

    @property
    def node_count(self) -> int:
        return int(self.actor.size)

    @classmethod
    def build(cls, config: FullTreeConfig = FullTreeConfig()) -> FullTree:
        states: list[PLOState] = []
        child_rows: list[list[int]] = []
        action_rows: list[list[int]] = []

        def visit(state: PLOState, raises: int) -> int:
            node = len(states)
            states.append(state)
            child_rows.append([-1, -1, -1])
            action_rows.append([-1, -1, -1])
            if state.terminal:
                return node
            cap = config.raise_caps[state.street]
            legal = [a for a in state.legal_actions() if a != Action.POT or raises < cap]
            if len(legal) > 3:
                raise RuntimeError("more than three legal actions")
            for slot, action in enumerate(legal):
                seat = state.actor
                amount = state.action_amount(action)
                is_raise = (action == Action.POT
                            and state.street_put[seat] + amount > state.current_bet + EPS)
                nxt = state.apply(action)
                carried = raises + int(is_raise) if nxt.street == state.street else 0
                child_rows[node][slot] = visit(nxt, carried)
                action_rows[node][slot] = ACTION_IDS[action.value]
            return node

        root = PLOState.new((config.stack_bb,) * 6, sb=0.5, bb=1.0, ante=0.0,
                            ante_mode="individual", opening_raise_mode="pot_only")
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 10_000))
        try:
            visit(root, 0)
        finally:
            sys.setrecursionlimit(limit)
        return cls._arrays(config, states, child_rows, action_rows)

    @classmethod
    def _arrays(cls, config, states, child_rows, action_rows) -> FullTree:
        count = len(states)
        actor = np.full(count, -1, dtype=np.int8)
        street = np.zeros(count, dtype=np.int8)
        decision_index = np.full(count, -1, dtype=np.int32)
        behind = np.empty((count, 6))
        sidepot_count = np.zeros(count, dtype=np.int8)
        sidepot_amount = np.zeros((count, 6))
        sidepot_eligible = np.zeros((count, 6), dtype=np.uint8)
        action_count = np.zeros(count, dtype=np.int8)
        row_start: list[int] = []
        rows = 0
        for node, state in enumerate(states):
            behind[node] = state.behind
            if not state.terminal:
                actor[node] = state.actor
                street[node] = state.street
                decision_index[node] = len(row_start)
                row_start.append(rows)
                rows += STREET_BUCKETS[state.street]
                action_count[node] = sum(1 for slot in child_rows[node] if slot >= 0)
                continue
            street[node] = min(state.street, 3)
            levels = sorted(value for value in set(state.committed) if value > 1e-9)
            previous = 0.0
            for layer, level in enumerate(levels):
                contributors = [s for s, amount in enumerate(state.committed) if amount + 1e-9 >= level]
                sidepot_amount[node, layer] = (level - previous) * len(contributors)
                sidepot_eligible[node, layer] = sum(1 << s for s in contributors if s not in state.folded)
                previous = level
            sidepot_count[node] = len(levels)
        children = np.asarray(child_rows, dtype=np.int32)
        first_in = []
        node = 0
        for seat in range(5):
            if actor[node] != seat:
                raise RuntimeError("first-in path does not reach the expected seat")
            first_in.append(node)
            node = int(children[node, 0])  # fold is always slot 0 when facing the blind
        return cls(
            config=config, actor=actor, street=street, decision_index=decision_index,
            children=children, action_ids=np.asarray(action_rows, dtype=np.int8),
            action_count=action_count, behind=behind, sidepot_count=sidepot_count,
            sidepot_amount=sidepot_amount, sidepot_eligible_mask=sidepot_eligible,
            first_in_nodes=np.asarray(first_in, dtype=np.int32),
            row_start=np.asarray(row_start, dtype=np.int64), rows=rows,
        )
