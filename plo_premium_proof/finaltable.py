"""Final-table and mid-tournament ICM solves: 2-7 seats, uneven stacks, payoffs in prize equity.

One spec is one table: every seat's stack in preflop order (UTG ... BTN, SB, BB), the
prizes still to be paid (1st, 2nd, ...), and the ante. Mid-tournament, ``players_left``
counts everyone still in and ``field_stack_bb`` is the average stack at the other tables;
those players are priced as one crowd (``pushfold.icm``) through a precomputed outcome table
(``mtticm``). The all-streets game is solved with
each hand scored by the change in Malmuth-Harville ICM equity instead of chips, so a chip
won is worth less than a chip lost. The run writes ``status.json`` as it goes and
``result.json`` (the range explorer's format) at every export and at the end. Creating
``stop`` in the output folder ends the run early with a final export.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numba
import numpy as np

from pushfold.icm import Payouts, PayoutError, value

from . import mtticm
from .fullkernels import icm_equity, no_outcomes, scratch_size, train_full
from .fulltree import FullTree, FullTreeConfig
from .solve import thread_seeds
from .tables import HandTables, comb_table, five_card_ranks
from .web_export import heads_up_tree

SEAT_NAMES = {
    2: ("SB", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("CO", "BTN", "SB", "BB"),
    5: ("HJ", "CO", "BTN", "SB", "BB"),
    6: ("UTG", "HJ", "CO", "BTN", "SB", "BB"),
    7: ("UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"),
}
MAX_SEATS = 7
DEFAULT_CAPS = (4, 1, 1, 1)
EXPORT_EVERY_SECONDS = 60.0
RESULT, STATUS, STOP = "result.json", "status.json", "stop"


class SpecError(ValueError):
    """The table description cannot be solved as given."""


@dataclasses.dataclass(frozen=True)
class FinalTableSpec:
    stacks: tuple[float, ...]            # bb, preflop order UTG ... BB
    payouts: tuple[float, ...]           # prize for 1st, 2nd, ... still to be paid
    ante_bb: float = 0.0
    ante_mode: str = "individual"        # everyone antes, or "bb": one big blind ante
    raise_caps: tuple[int, int, int, int] = DEFAULT_CAPS
    minutes: float = 30.0
    threads: int = 0                     # 0: every core
    seed: int = 1
    hero: str | None = None              # seat to open the explorer at
    hand: str | None = None              # hero's cards, e.g. "AsKsQd9c"
    players_left: int = 0                # whole tournament; 0 or the seat count: a final table
    field_stack_bb: float = 0.0          # average stack at the other tables
    label: str | None = None             # name shown for the solve

    def __post_init__(self) -> None:
        n = len(self.stacks)
        if not 2 <= n <= MAX_SEATS:
            raise SpecError(f"a final table here has 2-{MAX_SEATS} players, got {n}")
        if not all(0.2 <= x <= 400 for x in self.stacks):
            raise SpecError("every stack must be between 0.2bb and 400bb")
        if not self.payouts or any(p < 0 for p in self.payouts):
            raise SpecError("payouts must be a list of prizes, 1st place first")
        if list(self.payouts) != sorted(self.payouts, reverse=True):
            raise SpecError("payouts must not grow with place (1st is the largest)")
        if self.ante_mode not in ("individual", "bb"):
            raise SpecError("ante_mode must be individual or bb")
        if not 0 <= self.ante_bb < (5 if self.ante_mode == "bb" else 1):
            raise SpecError("ante is out of range")
        if len(self.raise_caps) != 4 or not 1 <= self.raise_caps[0] <= 5 or any(not 0 <= c <= 3 for c in self.raise_caps[1:]):
            raise SpecError("raise_caps: preflop 1-5 raises, postflop 0-3 per street")
        if not 0.5 <= self.minutes <= 24 * 60:
            raise SpecError("minutes must be between 0.5 and 1440")
        if self.hero is not None and self.hero not in self.seat_names:
            raise SpecError(f"hero must be one of {', '.join(self.seat_names)}")
        if self.players_left and self.players_left < n:
            raise SpecError("players_left counts this table too, so it cannot be below the seat count")
        if self.is_mtt:
            if not 0.2 <= self.field_stack_bb <= 2000:
                raise SpecError("field_stack_bb (average stack elsewhere) must be 0.2-2000bb")
            try:
                self.field_payouts.check(n)
            except PayoutError as error:
                raise SpecError(str(error)) from error

    @property
    def is_mtt(self) -> bool:
        return self.players_left > len(self.stacks)

    @property
    def field_payouts(self) -> Payouts:
        """Prizes for everyone still in, with the other tables as one crowd."""
        return Payouts(prizes=self.payouts[:self.players_left], crowd=self.players_left - len(self.stacks),
                       crowd_stack=self.field_stack_bb)

    @property
    def seat_names(self) -> tuple[str, ...]:
        return SEAT_NAMES[len(self.stacks)]

    @property
    def prizes(self) -> np.ndarray:
        """Prizes for places 1..n; places past the paid ones pay nothing."""
        paid = list(self.payouts[:len(self.stacks)])
        return np.asarray(paid + [0.0] * (len(self.stacks) - len(paid)), dtype=np.float64)

    def tree_config(self) -> FullTreeConfig:
        return FullTreeConfig(stack_bb=max(1.0, min(200.0, max(self.stacks))), raise_caps=self.raise_caps,
                              ante_bb=self.ante_bb, stacks=self.stacks, ante_mode=self.ante_mode)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FinalTableSpec:
        try:
            return cls(
                stacks=tuple(float(x) for x in data["stacks"]),
                payouts=tuple(float(x) for x in data["payouts"]),
                ante_bb=float(data.get("ante_bb", 0.0)),
                ante_mode=str(data.get("ante_mode", "individual")),
                raise_caps=tuple(int(x) for x in data.get("raise_caps", DEFAULT_CAPS)),
                minutes=float(data.get("minutes", 30.0)),
                threads=int(data.get("threads", 0)),
                seed=int(data.get("seed", 1)),
                hero=data.get("hero") or None,
                hand=data.get("hand") or None,
                players_left=int(data.get("players_left") or 0),
                field_stack_bb=float(data.get("field_stack_bb") or 0.0),
                label=data.get("label") or None,
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, SpecError):
                raise
            raise SpecError(f"bad table description: {error}") from error

    def to_dict(self) -> dict[str, Any]:
        return {**dataclasses.asdict(self), "seat_names": list(self.seat_names)}


def icm_table(stacks: tuple[float, ...], prizes: np.ndarray, field: Payouts | None = None) -> list[float]:
    """Each seat's prize equity for these chip counts (in prize money)."""
    chips = np.asarray(stacks, dtype=np.float64)
    if field is not None:
        in_chips = value(chips, tuple(stacks), field)[0]
        money = sum(field.prizes) / (chips.sum() + field.chips_away)
        return [float(x * money) for x in in_chips]
    work = np.empty(scratch_size(chips.size))
    return [float(icm_equity(chips, chips, prizes, seat, work)) for seat in range(chips.size)]


def _write(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(temporary, path)


def export_result(spec: FinalTableSpec, tree: FullTree, strategy_sum: np.ndarray, meta: dict[str, Any]) -> dict:
    """The explorer's JSON: the heads-up preflop tree with every bucket's average strategy."""
    buckets = HandTables.build().bucket_count

    def rows_of(node: int) -> np.ndarray:
        start = int(tree.row_start[tree.decision_index[node]])
        count = int(tree.action_count[node])
        block = np.asarray(strategy_sum[start:start + buckets, :count], dtype=np.float64)
        sums = block.sum(axis=1, keepdims=True)
        mix = np.where(sums > 0, block / np.where(sums > 0, sums, 1), 1.0 / count)
        return np.rint(mix * 255).astype(np.uint8)

    nodes, blob = heads_up_tree(spec.tree_config().root(), tree.actor, tree.children, tree.action_ids,
                                tree.action_count, rows_of, spec.seat_names)
    stacks = ", ".join(f"{name} {x:g}" for name, x in zip(spec.seat_names, spec.stacks))
    if spec.is_mtt:
        label = f"{spec.players_left} left · {len(spec.stacks)}-handed ICM"
        field = f" · field avg {spec.field_stack_bb:g}bb"
    else:
        label, field = f"Final table {len(spec.stacks)}-handed ICM", ""
    return {
        "name": "ft", "label": spec.label or label,
        "detail": f"{stacks}{field} · ante {spec.ante_bb:g}bb ({spec.ante_mode})",
        "stack": max(spec.stacks), "ante": spec.ante_bb, "buckets": buckets,
        "seats": list(spec.seat_names), "spec": spec.to_dict(),
        "icm": icm_table(spec.stacks, spec.prizes, spec.field_payouts if spec.is_mtt else None), "meta": meta,
        "nodes": nodes, "strategy": base64.b64encode(blob).decode(),
    }


def solve(spec: FinalTableSpec, out_dir: Path, *, epoch_deals: int = 40_000, discount_epochs: int = 200,
          clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """Run the ICM solve for ``spec.minutes``, keeping status.json and result.json current."""
    out_dir.mkdir(parents=True, exist_ok=True)
    started = clock()
    threads = spec.threads or os.cpu_count() or 1
    status: dict[str, Any] = {"state": "building", "spec": spec.to_dict(), "threads": threads,
                              "budget_seconds": spec.minutes * 60, "started": time.time()}
    _write(out_dir / STATUS, status)
    # Real tables almost never repeat their exact stacks, so a cached tree (~250MB at six
    # seats) would only fill the disk; rebuilding takes about 20 seconds.
    tree = FullTree.build(spec.tree_config(), cache_dir=None)
    tables = HandTables.build()
    rank5, comb = five_card_ranks(), comb_table()
    regrets = np.zeros((tree.rows, 3), dtype=np.float32)
    strategy_sum = np.zeros((tree.rows, 3), dtype=np.float32)
    states = thread_seeds(spec.seed, threads)
    per_thread = max(1, epoch_deals // threads)
    numba.set_num_threads(threads)
    if spec.is_mtt:
        # Crowd ICM priced once per terminal outcome, already in chips.
        status.update(state="pricing")
        _write(out_dir / STATUS, status)
        table = mtticm.build(tree, spec.field_payouts)
        outcomes = (table.start, table.winners, table.values)
        payouts = np.zeros(0)
        status["outcomes"] = int(table.values.shape[0])
    else:
        prizes = spec.prizes
        # ICM equity is in prize money; scale to about a big blind so float32 regrets stay precise.
        scale = float(prizes[0]) / sum(spec.stacks) if prizes[0] > 0 else 1.0
        payouts = prizes / scale
        outcomes = no_outcomes()
    solving = clock()
    status.update(state="solving", nodes=tree.node_count, decisions=tree.decision_count,
                  build_seconds=round(solving - started, 1))
    _write(out_dir / STATUS, status)
    epoch, exported = 0, solving
    stopped = False
    while clock() - solving < spec.minutes * 60:
        train_full(
            per_thread, states, tables.bucket_of, rank5, comb, tree.actor, tree.street,
            tree.decision_index, tree.row_start, tree.children, tree.action_count, tree.behind,
            tree.sidepot_count, tree.sidepot_amount, tree.sidepot_eligible_mask,
            regrets, strategy_sum, tree.start_stacks, payouts, *outcomes,
        )
        epoch += 1
        if epoch <= discount_epochs:  # linear CFR: early iterations fade out
            factor = np.float32(epoch / (epoch + 1))
            regrets *= factor
            strategy_sum *= factor
        now = clock()
        status.update(epochs=epoch, deals=epoch * per_thread * threads, seconds=round(now - solving, 1))
        if (out_dir / STOP).exists():
            stopped = True
            break
        if now - exported >= EXPORT_EVERY_SECONDS:
            _write(out_dir / RESULT, export_result(spec, tree, strategy_sum, _meta(status)))
            status["exported_at_seconds"] = status["seconds"]
            exported = now
        _write(out_dir / STATUS, status)
    result = export_result(spec, tree, strategy_sum, _meta(status))
    _write(out_dir / RESULT, result)
    status.update(state="stopped" if stopped else "done", exported_at_seconds=status.get("seconds", 0))
    _write(out_dir / STATUS, status)
    return status


def _meta(status: dict[str, Any]) -> dict[str, Any]:
    return {key: status.get(key) for key in ("epochs", "deals", "seconds", "threads", "nodes", "decisions",
                                             "outcomes")}
