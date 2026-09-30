"""Static public tree with betting on every street (pot-sized, capped, all-in aware)."""

from __future__ import annotations

import dataclasses
import sys
from array import array
from pathlib import Path

import numpy as np

from plo_icm.game import EPS, Action, PLOState

ACTION_IDS = {"fold": 0, "check": 1, "call": 2, "pot": 3}
# Per-street information buckets: preflop tier-pure, flop/turn draw-aware, river strength.
STREET_BUCKETS = (780, 120, 120, 10)
CACHE_DIR = Path(__file__).resolve().parents[1] / "tmp" / "plo_premium_proof" / "cache"


@dataclasses.dataclass(frozen=True)
class FullTreeConfig:
    stack_bb: float = 20.0
    raise_caps: tuple[int, int, int, int] = (3, 2, 2, 2)
    # Per-player ante, posted by everyone. It plays for the pot but, as on GGPoker, is left
    # out of the preflop pot-limit size (plo_icm.game handles both).
    ante_bb: float = 0.0

    def __post_init__(self) -> None:
        if not 1 <= self.stack_bb <= 200:
            raise ValueError("stack_bb must be between 1 and 200")
        if not 0 <= self.ante_bb < 1:
            raise ValueError("ante_bb must be in [0, 1)")
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
    def build(cls, config: FullTreeConfig = FullTreeConfig(), *, cache_dir: Path | None = CACHE_DIR) -> FullTree:
        """Build (or load from ``cache_dir``) the tree; nodes stream into compact arrays."""
        ante = f"-a{config.ante_bb:g}" if config.ante_bb else ""
        name = f"fulltree-{config.stack_bb:g}bb-{''.join(map(str, config.raise_caps))}{ante}.npz"
        cached = cache_dir / name if cache_dir is not None else None
        if cached is not None and cached.exists():
            return cls._load(config, cached)
        tree = cls._build(config)
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            tree._save(cached)
        return tree

    @classmethod
    def _build(cls, config: FullTreeConfig) -> FullTree:
        actor, street, count = array("b"), array("b"), array("b")
        children, action_ids = array("i"), array("b")
        behind, pot_amount = array("d"), array("d")
        pot_count, pot_mask = array("b"), array("B")
        row_start = array("q")
        rows = [0]

        def visit(state: PLOState, raises: int) -> int:
            node = len(actor)
            behind.extend(state.behind)
            children.extend((-1, -1, -1))
            action_ids.extend((-1, -1, -1))
            amounts, masks = [0.0] * 6, [0] * 6
            if state.terminal:
                actor.append(-1)
                street.append(min(state.street, 3))
                count.append(0)
                levels = sorted(value for value in set(state.committed) if value > 1e-9)
                previous = 0.0
                for layer, level in enumerate(levels):
                    contributors = [s for s, amount in enumerate(state.committed) if amount + 1e-9 >= level]
                    amounts[layer] = (level - previous) * len(contributors)
                    masks[layer] = sum(1 << s for s in contributors if s not in state.folded)
                    previous = level
                pot_count.append(len(levels))
                pot_amount.extend(amounts)
                pot_mask.extend(masks)
                return node
            cap = config.raise_caps[state.street]
            legal = [a for a in state.legal_actions() if a != Action.POT or raises < cap]
            if len(legal) > 3:
                raise RuntimeError("more than three legal actions")
            actor.append(state.actor)
            street.append(state.street)
            count.append(len(legal))
            pot_count.append(0)
            pot_amount.extend(amounts)
            pot_mask.extend(masks)
            row_start.append(rows[0])
            rows[0] += STREET_BUCKETS[state.street]
            for slot, action in enumerate(legal):
                seat = state.actor
                amount = state.action_amount(action)
                is_raise = (action == Action.POT
                            and state.street_put[seat] + amount > state.current_bet + EPS)
                nxt = state.apply(action)
                carried = raises + int(is_raise) if nxt.street == state.street else 0
                children[3 * node + slot] = visit(nxt, carried)
                action_ids[3 * node + slot] = ACTION_IDS[action.value]
            return node

        root = PLOState.new((config.stack_bb,) * 6, sb=0.5, bb=1.0, ante=config.ante_bb,
                            ante_mode="individual", opening_raise_mode="pot_only")
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 10_000))
        try:
            visit(root, 0)
        finally:
            sys.setrecursionlimit(limit)
        actor_np = np.frombuffer(actor, dtype=np.int8).copy()
        decision_index = np.full(actor_np.size, -1, dtype=np.int32)
        decisions = np.flatnonzero(actor_np >= 0)
        decision_index[decisions] = np.arange(decisions.size, dtype=np.int32)
        children_np = np.frombuffer(children, dtype=np.int32).reshape(-1, 3).copy()
        first_in, node = [], 0
        for seat in range(5):
            if actor_np[node] != seat:
                raise RuntimeError("first-in path does not reach the expected seat")
            first_in.append(node)
            node = int(children_np[node, 0])  # fold is always slot 0 when facing the blind
        return cls(
            config=config, actor=actor_np, street=np.frombuffer(street, dtype=np.int8).copy(),
            decision_index=decision_index, children=children_np,
            action_ids=np.frombuffer(action_ids, dtype=np.int8).reshape(-1, 3).copy(),
            action_count=np.frombuffer(count, dtype=np.int8).copy(),
            behind=np.frombuffer(behind, dtype=np.float64).reshape(-1, 6).copy(),
            sidepot_count=np.frombuffer(pot_count, dtype=np.int8).copy(),
            sidepot_amount=np.frombuffer(pot_amount, dtype=np.float64).reshape(-1, 6).copy(),
            sidepot_eligible_mask=np.frombuffer(pot_mask, dtype=np.uint8).reshape(-1, 6).copy(),
            first_in_nodes=np.asarray(first_in, dtype=np.int32),
            row_start=np.frombuffer(row_start, dtype=np.int64).copy(), rows=rows[0],
        )

    _ARRAYS = ("actor", "street", "decision_index", "children", "action_ids", "action_count", "behind",
               "sidepot_count", "sidepot_amount", "sidepot_eligible_mask", "first_in_nodes", "row_start")

    def _save(self, path: Path) -> None:
        temporary = path.with_suffix(".tmp.npz")
        np.savez(temporary, rows=np.asarray(self.rows), **{name: getattr(self, name) for name in self._ARRAYS})
        temporary.replace(path)

    @classmethod
    def _load(cls, config: FullTreeConfig, path: Path) -> FullTree:
        with np.load(path) as data:
            return cls(config=config, rows=int(data["rows"]), **{name: data[name] for name in cls._ARRAYS})
