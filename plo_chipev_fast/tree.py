"""Complete, unmerged static public tree matching :mod:`plo_chipev.game`."""

from __future__ import annotations

import dataclasses
import hashlib

import numpy as np

from plo_chipev.game import PreflopState

ACTION_NAMES = ("fold", "check", "call", "pot")
ACTION_IDS = {name: index for index, name in enumerate(ACTION_NAMES)}


@dataclasses.dataclass(frozen=True)
class PublicTree:
    actor: np.ndarray
    decision_index: np.ndarray
    children: np.ndarray
    action_ids: np.ndarray
    action_count: np.ndarray
    behind: np.ndarray
    committed: np.ndarray
    folded_mask: np.ndarray
    dead_money: np.ndarray
    sidepot_count: np.ndarray
    sidepot_amount: np.ndarray
    sidepot_contributors_mask: np.ndarray
    sidepot_eligible_mask: np.ndarray
    histories: tuple[tuple[str, ...], ...]
    history_to_node: dict[tuple[str, ...], int]

    @property
    def node_count(self) -> int:
        return int(self.actor.size)

    @property
    def decision_count(self) -> int:
        return int(np.count_nonzero(self.actor >= 0))

    @property
    def terminal_count(self) -> int:
        return int(np.count_nonzero(self.actor < 0))

    @classmethod
    def build(cls) -> PublicTree:
        states: list[PreflopState] = []
        children_rows: list[list[int]] = []
        action_rows: list[list[int]] = []
        counts: list[int] = []
        history_to_node: dict[tuple[str, ...], int] = {}

        def visit(state: PreflopState) -> int:
            if state.history in history_to_node:
                raise RuntimeError("public histories must not merge")
            node = len(states)
            history_to_node[state.history] = node
            states.append(state)
            children_rows.append([-1, -1, -1])
            action_rows.append([-1, -1, -1])
            legal = state.legal_actions()
            counts.append(len(legal))
            for offset, action in enumerate(legal):
                child = visit(state.apply(action))
                children_rows[node][offset] = child
                action_rows[node][offset] = ACTION_IDS[action.value]
            return node

        visit(PreflopState.new())
        node_count = len(states)
        actor = np.full(node_count, -1, dtype=np.int8)
        decision_index = np.full(node_count, -1, dtype=np.int32)
        behind = np.empty((node_count, 6), dtype=np.float64)
        committed = np.empty((node_count, 6), dtype=np.float64)
        folded_mask = np.zeros(node_count, dtype=np.uint8)
        dead_money = np.empty(node_count, dtype=np.float64)
        sidepot_count = np.zeros(node_count, dtype=np.int8)
        sidepot_amount = np.zeros((node_count, 6), dtype=np.float64)
        sidepot_contributors_mask = np.zeros((node_count, 6), dtype=np.uint8)
        sidepot_eligible_mask = np.zeros((node_count, 6), dtype=np.uint8)
        next_decision = 0
        for node, state in enumerate(states):
            if not state.terminal:
                assert state.actor is not None
                actor[node] = state.actor
                decision_index[node] = next_decision
                next_decision += 1
            behind[node] = state.base.behind
            committed[node] = state.base.committed
            folded_mask[node] = sum(1 << seat for seat in state.base.folded)
            dead_money[node] = state.base.dead_money
            if state.terminal:
                levels = sorted(value for value in set(state.base.committed) if value > 1e-9)
                previous = 0.0
                for layer, level in enumerate(levels):
                    contributors = tuple(
                        seat
                        for seat, amount in enumerate(state.base.committed)
                        if amount + 1e-9 >= level
                    )
                    eligible = tuple(
                        seat for seat in contributors if seat not in state.base.folded
                    )
                    sidepot_amount[node, layer] = (level - previous) * len(contributors)
                    if layer == 0:
                        sidepot_amount[node, layer] += state.base.dead_money
                    sidepot_contributors_mask[node, layer] = sum(
                        1 << seat for seat in contributors
                    )
                    sidepot_eligible_mask[node, layer] = sum(1 << seat for seat in eligible)
                    previous = level
                if not levels and state.base.dead_money > 1e-9:
                    sidepot_amount[node, 0] = state.base.dead_money
                    sidepot_eligible_mask[node, 0] = sum(
                        1 << seat for seat in range(6) if seat not in state.base.folded
                    )
                    levels = [state.base.dead_money]
                sidepot_count[node] = len(levels)
        tree = cls(
            actor=actor,
            decision_index=decision_index,
            children=np.asarray(children_rows, dtype=np.int32),
            action_ids=np.asarray(action_rows, dtype=np.int8),
            action_count=np.asarray(counts, dtype=np.int8),
            behind=behind,
            committed=committed,
            folded_mask=folded_mask,
            dead_money=dead_money,
            sidepot_count=sidepot_count,
            sidepot_amount=sidepot_amount,
            sidepot_contributors_mask=sidepot_contributors_mask,
            sidepot_eligible_mask=sidepot_eligible_mask,
            histories=tuple(state.history for state in states),
            history_to_node=history_to_node,
        )
        if (tree.node_count, tree.decision_count, tree.terminal_count) != (11_566, 5_466, 6_100):
            raise RuntimeError("unexpected public-tree shape")
        return tree

    def representation_hash(self) -> str:
        digest = hashlib.sha256(b"plo-chipev-fast-public-tree-v1")
        for array in (
            self.actor,
            self.decision_index,
            self.children,
            self.action_ids,
            self.action_count,
            self.behind,
            self.committed,
            self.folded_mask,
            self.dead_money,
            self.sidepot_count,
            self.sidepot_amount,
            self.sidepot_contributors_mask,
            self.sidepot_eligible_mask,
        ):
            digest.update(array.dtype.str.encode())
            digest.update(str(array.shape).encode())
            digest.update(array.tobytes(order="C"))
        for history in self.histories:
            digest.update(b"\0".join(item.encode() for item in history))
            digest.update(b"\xff")
        return digest.hexdigest()


def settle_terminal(tree: PublicTree, node: int, ranks: np.ndarray) -> np.ndarray:
    """Settle every main/side-pot share for a terminal static-tree node."""
    if not 0 <= node < tree.node_count or tree.actor[node] >= 0:
        raise ValueError("node must be terminal")
    if ranks.shape != (6,) or not np.isfinite(ranks).all():
        raise ValueError("ranks must contain six finite values")
    out = tree.behind[node].copy()
    for layer in range(int(tree.sidepot_count[node])):
        eligible_mask = int(tree.sidepot_eligible_mask[node, layer])
        eligible = [seat for seat in range(6) if eligible_mask & (1 << seat)]
        if not eligible:
            raise RuntimeError("pot has no eligible player")
        best = min(int(ranks[seat]) for seat in eligible)
        winners = [seat for seat in eligible if int(ranks[seat]) == best]
        for seat in winners:
            out[seat] += float(tree.sidepot_amount[node, layer]) / len(winners)
    expected = float(
        tree.behind[node].sum() + tree.committed[node].sum() + tree.dead_money[node]
    )
    if not np.isclose(out.sum(), expected, atol=1e-7):
        raise RuntimeError("chip conservation failure")
    return out
