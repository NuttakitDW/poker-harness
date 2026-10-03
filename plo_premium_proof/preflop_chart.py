"""Compact preflop charts from the all-streets solves, and exact spot lookup.

A chart holds, for every preflop decision node of a solved game, the seed-averaged average
strategy of each of the 780 tier-pure hand buckets, plus the preflop part of the public tree.
Strategies are stored as uint8 (probability x 255) in a memory-mapped .npy, so one lookup
touches only one row.

Spots are replayed as action lines: scripted voluntary actions in order, every other player
folds (or checks when folding is not legal), and the walk stops at the hero's decision.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from plo_icm.game import Action, PLOState

from .fulltree import STREET_BUCKETS, FullTreeConfig  # plain Python + numpy; no numba here

SEATS = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
ACTION_NAMES = ("fold", "check", "call", "pot")
CHART_DIR = Path(__file__).resolve().parents[1] / "tmp" / "plo_premium_proof" / "charts"
def colex_index(cards: tuple[int, ...]) -> int:
    return sum(math.comb(card, offset) for offset, card in enumerate(sorted(cards), 1))


_CARD_ID = {r + s: 4 * i + j for i, r in enumerate("23456789TJQKA") for j, s in enumerate("cdhs")}


class SpotError(ValueError):
    """The requested line does not exist in the solved game."""


def export_chart(models: Iterable[Path], config: FullTreeConfig, out_dir: Path, meta: dict) -> Path:
    """Average the preflop strategy of several seeds and write a chart directory."""
    from .fullsolve import load_full  # needs numba; only the exporter imports it
    from .fulltree import FullTree
    from .tables import HandTables
    tree = FullTree.build(config)
    tables = HandTables.build()
    buckets = tables.bucket_count
    pre = np.flatnonzero((tree.actor >= 0) & (tree.street == 0))
    local = np.full(tree.node_count, -1, dtype=np.int64)
    local[pre] = np.arange(pre.size)
    total = np.zeros((pre.size, buckets, 3))
    models = list(models)
    for path in models:
        strategy_sum, _ = load_full(path)
        for i, node in enumerate(pre):
            start = int(tree.row_start[tree.decision_index[node]])
            count = int(tree.action_count[node])
            block = np.asarray(strategy_sum[start:start + buckets, :count], dtype=np.float64)
            sums = block.sum(axis=1, keepdims=True)
            total[i, :, :count] += np.where(sums > 0, block / np.where(sums > 0, sums, 1), 1.0 / count)
        del strategy_sum
    mix = total / len(models)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "strategy.npy", np.rint(mix * 255).astype(np.uint8))
    children = tree.children[pre]
    np.savez(
        out_dir / "tree.npz",
        nodes=pre, actor=tree.actor[pre], action_ids=tree.action_ids[pre],
        action_count=tree.action_count[pre],
        children_local=np.where(children >= 0, local[np.maximum(children, 0)], -1),
        bucket_of=tables.bucket_of.astype(np.int16),
    )
    info = {**meta, "stack_bb": config.stack_bb, "ante_bb": config.ante_bb,
            "start_stack_bb": float(config.seat_stacks[0]),
            "raise_caps": list(config.raise_caps), "seeds": len(models), "buckets": buckets,
            "preflop_decisions": int(pre.size), "street_buckets": list(STREET_BUCKETS)}
    (out_dir / "meta.json").write_text(json.dumps(info, indent=1))
    return out_dir


@dataclasses.dataclass(frozen=True)
class Option:
    action: str        # fold | check | call | pot
    amount: float      # chips added now (bb); 0 for fold/check
    total: float       # hero's total street commitment after the action (bb)
    all_in: bool
    frequency: float   # 0..1


@dataclasses.dataclass(frozen=True)
class Decision:
    spot: str
    line: tuple[str, ...]
    pot: float
    to_call: float
    options: tuple[Option, ...]

    @property
    def best(self) -> Option:
        return max(self.options, key=lambda o: o.frequency)


class Chart:
    """One solved game's preflop chart."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.meta = json.loads((directory / "meta.json").read_text())
        with np.load(directory / "tree.npz") as data:
            self.actor = data["actor"]
            self.action_ids = data["action_ids"]
            self.action_count = data["action_count"]
            self.children = data["children_local"]
            self.bucket_of = data["bucket_of"]
        self.strategy = np.load(directory / "strategy.npy", mmap_mode="r")

    @property
    def stack(self) -> float:
        return float(self.meta["stack_bb"])

    @property
    def start_stack(self) -> float:
        """Each seat's stack before posting anything (stack plus ante when the ante is on top)."""
        return float(self.meta.get("start_stack_bb", self.meta["stack_bb"]))

    @property
    def seats(self) -> int:
        return int(self.meta.get("seats", 6))

    @property
    def ante(self) -> float:
        return float(self.meta["ante_bb"])

    def bucket(self, cards: tuple[str, ...]) -> int:
        ids = tuple(sorted(_CARD_ID[c[0].upper() + c[1].lower()] for c in cards))
        if len(ids) != 4 or len(set(ids)) != 4:
            raise SpotError("a PLO hand needs four different cards")
        return int(self.bucket_of[colex_index(ids)])

    def decide(self, cards: tuple[str, ...], hero: str, events: list[tuple[str, str]], spot: str) -> Decision:
        """The hero's mix at the end of a scripted line (see ``walk``)."""
        node, state, line = self.walk(hero, events)
        return self._decision(node, state, line, SEATS.index(hero), self.bucket(cards), spot)

    def walk(self, hero: str, events: list[tuple[str, str]]) -> tuple[int, PLOState, list[str]]:
        """Walk ``events`` [(seat, fold|call|pot|check), ...]; others fold; stop at hero."""
        hero_seat = SEATS.index(hero)
        state = PLOState.new((self.stack,) * 6, sb=0.5, bb=1.0, ante=self.ante, ante_mode="individual",
                             opening_raise_mode="pot_only")
        node, line = 0, []
        pending = [(SEATS.index(seat), action) for seat, action in events]
        while True:
            if node < 0 or state.terminal or state.street > 0:
                raise SpotError("the line ends before the hero acts")
            seat = int(self.actor[node])
            if seat == hero_seat and not pending:
                break
            if pending and pending[0][0] == seat:
                wanted = pending.pop(0)[1]
            elif seat == hero_seat:
                raise SpotError(f"{hero} would have to act before {SEATS[pending[0][0]]} in this line")
            else:
                wanted = "fold"
            names = [ACTION_NAMES[a] for a in self.action_ids[node, :self.action_count[node]]]
            if wanted == "fold" and "fold" not in names:
                wanted = "check" if "check" in names else wanted
            if wanted == "pot" and "pot" not in names:
                raise SpotError(f"{SEATS[seat]} cannot raise here (raise cap or all-in)")
            if wanted not in names:
                raise SpotError(f"{SEATS[seat]} cannot {wanted} here")
            slot = names.index(wanted)
            action = Action(wanted)
            amount = state.action_amount(action)
            line.append(f"{SEATS[seat]} {self._verb(state, action, amount)}")
            state = state.apply(action)
            node = int(self.children[node, slot])
        return node, state, line

    def options(self, node: int, state: PLOState, hero_seat: int) -> list[tuple[str, float, float, bool]]:
        """(action, chips added, total street commitment, all-in) for each legal action."""
        out = []
        for name in (ACTION_NAMES[a] for a in self.action_ids[node, :self.action_count[node]]):
            amount = state.action_amount(Action(name))
            out.append((name, amount, state.street_put[hero_seat] + amount,
                        math.isclose(amount, state.behind[hero_seat]) and amount > 0))
        return out

    def _decision(self, node: int, state: PLOState, line: list[str], hero_seat: int, bucket: int,
                  spot: str) -> Decision:
        names = [ACTION_NAMES[a] for a in self.action_ids[node, :self.action_count[node]]]
        probs = self.strategy[node, bucket, :len(names)].astype(np.float64) / 255.0
        probs = probs / probs.sum() if probs.sum() > 0 else np.full(len(names), 1.0 / len(names))
        options = [Option(name, amount, total, all_in, float(p))
                   for (name, amount, total, all_in), p in zip(self.options(node, state, hero_seat), probs)]
        to_call = max(0.0, state.current_bet - state.street_put[hero_seat])
        return Decision(spot, tuple(line), float(state.pot), float(to_call), tuple(options))

    @staticmethod
    def _verb(state: PLOState, action: Action, amount: float) -> str:
        if action == Action.FOLD:
            return "fold"
        if action == Action.CHECK:
            return "check"
        seat = state.actor
        total = state.street_put[seat] + amount
        if action == Action.CALL:
            return "limp" if state.current_bet <= state.big_blind + 1e-9 else f"call {total:g}"
        return f"raise to {total:g}"


# Six-max names for seats that other table sizes call differently (LJ is the first seat in 6-max).
SEAT_ALIASES = {"LJ": "UTG", "EP": "UTG", "UTG+1": "HJ", "MP": "HJ"}


def six_max_seat(name: str | None) -> str | None:
    """Canonical 6-max seat for a parsed seat name, or None when it has no 6-max equivalent."""
    if name is None:
        return None
    name = SEAT_ALIASES.get(name.upper(), name.upper())
    return name if name in SEATS else None


def spot_events(hero: str, villain: str | None, scenario: str | None) -> tuple[list[tuple[str, str]], str]:
    """Translate (hero, villain, scenario) into a scripted preflop line."""
    order = {seat: i for i, seat in enumerate(SEATS)}
    for seat in (hero, villain):
        if seat is not None and seat not in order:
            raise SpotError(f"{seat} is not a 6-max seat (UTG, HJ, CO, BTN, SB, BB)")
    kind = (scenario or "RFI").upper().replace("-", "")
    if villain is None:
        if kind not in ("RFI", ""):
            raise SpotError("say who opened or raised, for example 'BTN vs CO open'")
        return [], "first in"
    if villain == hero:
        raise SpotError("hero and villain are the same seat")
    villain_first = order[villain] < order[hero]
    if kind == "LIMP":
        if not villain_first:
            raise SpotError(f"{villain} acts after {hero}, so {hero} cannot face that limp")
        return [(villain, "call")], f"vs {villain} limp"
    if kind in ("RFI", "OPEN", "RAISE"):
        if not villain_first:
            raise SpotError(f"{villain} acts after {hero}; an open from {villain} would come after {hero} folded")
        return [(villain, "pot")], f"vs {villain} open"
    if kind == "3BET":
        if villain_first:  # hero is considering a 3-bet against the villain's open
            return [(villain, "pot")], f"vs {villain} open"
        return [(hero, "pot"), (villain, "pot")], f"open, vs {villain} 3-bet"
    if kind == "4BET":
        if villain_first:
            return [(villain, "pot"), (hero, "pot"), (villain, "pot")], f"3-bet, vs {villain} 4-bet"
        return [(hero, "pot"), (villain, "pot")], f"open, vs {villain} 3-bet"
    if kind == "5BET":
        if villain_first:
            raise SpotError("a 5-bet facing spot needs the hero to have opened and 4-bet")
        return [(hero, "pot"), (villain, "pot"), (hero, "pot"), (villain, "pot")], f"4-bet, vs {villain} 5-bet"
    raise SpotError(f"unsupported scenario: {scenario}")


_CHARTS: dict[str, Chart] = {}


def chart(name: str) -> Chart:
    if name not in _CHARTS:
        directory = CHART_DIR / name
        if not (directory / "meta.json").exists():
            raise FileNotFoundError(f"chart {name} is not built; run python -m plo_premium_proof export-chart")
        _CHARTS[name] = Chart(directory)
    return _CHARTS[name]
