"""The complete public betting tree as flat arrays for the native trainer.

Each decision node has three action slots: 0 fold, 1 check or call, 2 bet or raise; -1 marks an illegal
slot. Card buckets are looked up by the node's street.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from .game import BettingState, Rules

DECISION, FOLD, SHOWDOWN = 0, 1, 2
SLOT = {"f": 0, "k": 1, "c": 1, "b": 2, "r": 2}


@dataclasses.dataclass(frozen=True)
class PublicTree:
    rules: Rules
    kind: np.ndarray  # DECISION, FOLD or SHOWDOWN
    actor: np.ndarray  # -1 at terminals
    street: np.ndarray
    children: np.ndarray  # (nodes, 3)
    committed: np.ndarray  # (nodes, 2)
    folder: np.ndarray  # -1 unless kind == FOLD
    decision_index: np.ndarray  # dense id per decision node, -1 elsewhere
    histories: tuple[str, ...]
    history_to_node: dict[str, int]

    @property
    def node_count(self) -> int:
        return int(self.kind.size)

    @property
    def decision_count(self) -> int:
        return int(np.count_nonzero(self.kind == DECISION))

    @classmethod
    def build(cls, rules: Rules = Rules()) -> PublicTree:
        states: list[BettingState] = []
        children: list[list[int]] = []

        def visit(state: BettingState) -> int:
            node = len(states)
            states.append(state)
            children.append([-1, -1, -1])
            for action in state.legal():
                children[node][SLOT[action]] = visit(state.apply(action))
            return node

        visit(BettingState.new(rules))
        n = len(states)
        kind = np.array([DECISION if not s.terminal else FOLD if s.folder is not None else SHOWDOWN
                         for s in states], dtype=np.int8)
        decision_index = np.full(n, -1, dtype=np.int32)
        decision_index[kind == DECISION] = np.arange(int(np.count_nonzero(kind == DECISION)), dtype=np.int32)
        histories = tuple(s.history for s in states)
        return cls(
            rules=rules,
            kind=kind,
            actor=np.array([-1 if s.terminal else s.actor for s in states], dtype=np.int8),
            street=np.array([s.street for s in states], dtype=np.int8),
            children=np.array(children, dtype=np.int32),
            committed=np.array([s.committed for s in states], dtype=np.float64),
            folder=np.array([-1 if s.folder is None else s.folder for s in states], dtype=np.int8),
            decision_index=decision_index,
            histories=histories,
            history_to_node={h: i for i, h in enumerate(histories)},
        )
