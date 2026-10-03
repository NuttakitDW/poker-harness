"""Solve and audit the all-streets game (default 20bb, 4-bet, pot-sized postflop)."""

from __future__ import annotations

import dataclasses
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any

import numba
import numpy as np

from .fulltree import STREET_BUCKETS, FullTree, FullTreeConfig
from .fullkernels import evaluate_root_actions, no_outcomes, sample_root_actions, train_full, tree_links
from .solve import thread_seeds
from .tables import (
    FIRST_IN_POSITIONS,
    HandTables,
    colex_index,
    comb_table,
    five_card_ranks,
    hand_classes,
    select_classes,
)
from .verify import Z_CRITICAL, _ratio, hwang_form

SCHEMA = "plo-premium-proof-full-v1"
ROOT_LABELS = {0: "fold", 2: "limp", 3: "pot_open"}
CHIP_EV = np.zeros(0)  # no payouts: the kernels score chips


@dataclasses.dataclass(frozen=True)
class FullSolveConfig:
    seconds: float
    stack_bb: float = 20.0
    raise_caps: tuple[int, int, int, int] = (3, 2, 2, 2)
    ante_bb: float = 0.0
    single_precision: bool = False
    threads: int = 12
    seed: int = 1
    epoch_deals: int = 200_000
    discount_epochs: int = 100
    checkpoint_every: int = 20
    seats: int = 6
    # True: stack_bb is what each player has after posting the ante (the ante is added on top).
    ante_on_top: bool = False

    def __post_init__(self) -> None:
        if not self.seconds > 0 or self.threads < 1 or self.epoch_deals < self.threads:
            raise ValueError("invalid solve budget")
        if not 2 <= self.seats <= 6:
            raise ValueError("seats must be 2-6")

    def tree_config(self) -> FullTreeConfig:
        return tree_config(self.stack_bb, self.raise_caps, self.ante_bb, self.seats, self.ante_on_top)


def tree_config(stack_bb: float, raise_caps, ante_bb: float, seats: int = 6, ante_on_top: bool = False) -> FullTreeConfig:
    """The game tree for a symmetric table; six seats without ante_on_top keeps the old cache names."""
    if seats == 6 and not ante_on_top:
        return FullTreeConfig(stack_bb=stack_bb, raise_caps=tuple(raise_caps), ante_bb=ante_bb)
    start = stack_bb + (ante_bb if ante_on_top else 0.0)
    return FullTreeConfig(stack_bb=stack_bb, raise_caps=tuple(raise_caps), ante_bb=ante_bb, stacks=(start,) * seats)


def meta_tree_config(meta: dict) -> FullTreeConfig:
    return tree_config(meta["stack_bb"], meta["raise_caps"], meta.get("ante_bb", 0.0), meta.get("seats", 6),
                       meta.get("ante_on_top", False))


def _save(path: Path, strategy_sum: np.ndarray, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.npz")
    np.savez(temporary, strategy_sum=strategy_sum, meta=json.dumps(meta))
    os.replace(temporary, path)


def load_full(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    with np.load(path) as data:
        meta = json.loads(str(data["meta"]))
        if meta.get("schema") != SCHEMA:
            raise ValueError(f"{path} is not a {SCHEMA} checkpoint")
        return data["strategy_sum"], meta


def solve_full(config: FullSolveConfig, output: Path, *, log=print) -> dict[str, Any]:
    tree = FullTree.build(config.tree_config())
    tables = HandTables.build()
    rank5, comb = five_card_ranks(), comb_table()
    dtype = np.float32 if config.single_precision else np.float64
    regrets = np.zeros((tree.rows, 3), dtype=dtype)
    strategy_sum = np.zeros((tree.rows, 3), dtype=dtype)
    states = thread_seeds(config.seed, config.threads)
    per_thread = config.epoch_deals // config.threads
    numba.set_num_threads(config.threads)
    started = time.perf_counter()
    epoch = 0

    def checkpoint() -> dict[str, Any]:
        meta = {
            "schema": SCHEMA, "seed": config.seed, "stack_bb": config.stack_bb, "ante_bb": config.ante_bb,
            "seats": config.seats, "ante_on_top": config.ante_on_top,
            "start_stack_bb": float(tree.start_stacks[0]),
            "raise_caps": list(tree.config.raise_caps), "street_buckets": list(STREET_BUCKETS),
            "epochs": epoch, "deals": epoch * per_thread * config.threads,
            "traversals": config.seats * epoch * per_thread * config.threads,
            "seconds": time.perf_counter() - started, "dtype": str(np.dtype(dtype)),
            "game": f"PLO4 {config.seats}-max chip EV, pot-sized bets on all streets, all-in capped",
        }
        _save(output / "model.npz", strategy_sum, meta)
        return meta

    while time.perf_counter() - started < config.seconds:
        train_full(
            per_thread, states, tables.bucket_of, rank5, comb, tree.actor, tree.street,
            tree.decision_index, tree.row_start, tree.children, tree.action_count, tree.behind,
            tree.sidepot_count, tree.sidepot_amount, tree.sidepot_eligible_mask,
            regrets, strategy_sum, tree.start_stacks, CHIP_EV, *no_outcomes(),
        )
        epoch += 1
        if epoch <= config.discount_epochs:
            factor = dtype(epoch / (epoch + 1))
            regrets *= factor
            strategy_sum *= factor
        if epoch % config.checkpoint_every == 0:
            meta = checkpoint()
            log(json.dumps({"epoch": epoch, "deals": meta["deals"], "seconds": round(meta["seconds"])}),
                flush=True)
    return checkpoint()


def row_policy(strategy_sum: np.ndarray, tree: FullTree) -> np.ndarray:
    """Normalized average strategy per row; unvisited rows are uniform over legal actions."""
    decision_nodes = np.flatnonzero(tree.actor >= 0)
    order = np.argsort(tree.decision_index[decision_nodes])
    nodes = decision_nodes[order]
    widths = np.asarray([STREET_BUCKETS[s] for s in tree.street[nodes]])
    legal = np.repeat(tree.action_count[nodes].astype(np.int64), widths)
    totals = strategy_sum.sum(axis=1)
    policy = np.zeros_like(strategy_sum)
    seen = totals > 0
    policy[seen] = strategy_sum[seen] / totals[seen, None]
    mask = np.arange(3)[None, :] < legal[:, None]
    uniform = mask / legal[:, None]
    policy[~seen] = uniform[~seen]
    return policy


def _root_mix(strategy_sum: np.ndarray, row: int, count: int) -> np.ndarray:
    weights = np.asarray(strategy_sum[row, :count], dtype=np.float64)
    total = weights.sum()
    return weights / total if total > 0 else np.full(count, 1.0 / count)


def _rows(pairs, moments, strategy_sum, tree, tables, labels_by_seat):
    rows = []
    for index, (hand, seat) in enumerate(pairs):
        labels = labels_by_seat[seat]
        sum_z, sum_z2 = moments[index, 3, 0], moments[index, 3, 1]
        estimates = [_ratio(*moments[index, a, :3], sum_z, sum_z2) for a in range(len(labels))]
        root = int(tree.first_in_nodes[seat])
        row = int(tree.row_start[tree.decision_index[root]] + tables.bucket_of[colex_index(hand.cards)])
        mix = _root_mix(strategy_sum, row, len(labels))
        fold = estimates[0].mean
        best = max(range(1, len(labels)), key=lambda a: estimates[a].mean)
        if estimates[best].mean - Z_CRITICAL * estimates[best].se > fold:
            verdict = "must_not_fold"
        elif all(e.mean + Z_CRITICAL * e.se < fold for e in estimates[1:]):
            verdict = "fold_beats_every_deviation"
        else:
            verdict = "inconclusive"
        rows.append({
            "hand": hand.text, "combos": hand.combos, "tier": hand.tier,
            "position": FIRST_IN_POSITIONS[seat], "actions": labels,
            "solver_frequency": dict(zip(labels, map(float, mix))),
            "ev": {l: e.mean for l, e in zip(labels, estimates)},
            "se": {l: e.se for l, e in zip(labels, estimates)},
            "root_deviation_gain": max(e.mean for e in estimates)
            - float(sum(p * e.mean for p, e in zip(mix, estimates))),
            "verdict": verdict,
        })
    return rows


def verify_full(model: Path, *, samples: int, threads: int, seed: int,
                positions: tuple[str, ...] = FIRST_IN_POSITIONS, limit: int | None = None,
                other_classes: int = 0, tier: str = "Premium", per_tier: int | None = None,
                sampled: bool = False, log=print) -> dict[str, Any]:
    started = time.perf_counter()
    strategy_sum, meta = load_full(model)
    tree = FullTree.build(FullTreeConfig(stack_bb=meta["stack_bb"], raise_caps=tuple(meta["raise_caps"]),
                                         ante_bb=meta.get("ante_bb", 0.0)))
    if strategy_sum.shape != (tree.rows, 3):
        raise ValueError("checkpoint does not match the rebuilt tree")
    tables = HandTables.build()
    policy = None if sampled else row_policy(strategy_sum, tree)
    rank5, comb = five_card_ranks(), comb_table()
    parent, parent_slot, subtree_end = tree_links(tree.children, tree.action_count, tree.actor)
    numba.set_num_threads(threads)
    seats = [FIRST_IN_POSITIONS.index(name) for name in positions]
    labels_by_seat = {
        seat: [ROOT_LABELS[int(a)] for a in tree.action_ids[tree.first_in_nodes[seat],
                                                            :tree.action_count[tree.first_in_nodes[seat]]]]
        for seat in range(5)
    }

    def run(classes, run_seed):
        pairs = [(hand, seat) for hand in classes for seat in seats]
        moments = np.zeros((len(pairs), 4, 3))
        if sampled:
            sample_root_actions(
                np.asarray([h.cards for h, _ in pairs], dtype=np.int64),
                np.asarray([s for _, s in pairs], dtype=np.int64),
                thread_seeds(run_seed, len(pairs)), samples, tree.first_in_nodes, tables.bucket_of,
                rank5, comb, strategy_sum, tree.actor, tree.street, tree.decision_index, tree.row_start,
                tree.children, tree.action_count, tree.behind, tree.sidepot_count, tree.sidepot_amount,
                tree.sidepot_eligible_mask, tree.start_stacks, CHIP_EV, moments, *no_outcomes(),
            )
            return _rows(pairs, moments, strategy_sum, tree, tables, labels_by_seat)
        evaluate_root_actions(
            np.asarray([h.cards for h, _ in pairs], dtype=np.int64),
            np.asarray([s for _, s in pairs], dtype=np.int64),
            thread_seeds(run_seed, len(pairs)), math.ceil(samples / 32), tree.first_in_nodes,
            tables.bucket_of, rank5, comb, policy, tree.actor, tree.street, tree.decision_index,
            tree.row_start, tree.action_count, tree.behind, tree.sidepot_count,
            tree.sidepot_amount, tree.sidepot_eligible_mask, parent, parent_slot, subtree_end,
            1e-9, tree.start_stacks, CHIP_EV, moments, *no_outcomes(),
        )
        return _rows(pairs, moments, strategy_sum, tree, tables, labels_by_seat)

    premium, weights = select_classes(tables, tier, per_tier=per_tier, limit=limit, seed=seed)
    log(f"{tier} classes {len(premium)} x seats {positions}", flush=True)
    rows = run(premium, seed)
    forms = {hand.text: hwang_form(hand) for hand in premium}
    weight_of = {hand.text: weight for hand, weight in zip(premium, weights)}
    for row in rows:
        row["form"] = forms[row["hand"]]
        row["sample_weight"] = weight_of[row["hand"]]
    others: list[dict[str, Any]] = []
    if other_classes:
        everyone = list(hand_classes(tables))
        others = run(random.Random(seed).sample(everyone, other_classes), seed + 1)
    summary = {}
    for position in positions:
        subset = [r for r in rows if r["position"] == position]
        combos: dict[str, int] = {}
        for r in subset:
            combos[r["verdict"]] = combos.get(r["verdict"], 0) + r["sample_weight"]
        total = sum(r["sample_weight"] for r in subset)
        summary[position] = {
            "verdict_combos": combos,
            "solver_fold": sum(r["sample_weight"] * r["solver_frequency"]["fold"] for r in subset) / total,
            "mean_root_deviation_gain_all_tiers": (
                float(np.mean([r["root_deviation_gain"] for r in others if r["position"] == position]))
                if others else None),
        }
    return {"schema": "plo-premium-proof-full-report-v1", "tier": tier, "per_tier": per_tier,
            "model_meta": meta, "samples": samples, "evaluator": "sampled paths" if sampled else "full width",
            "summary": summary, "premium_rows": rows, "other_rows": others,
            "seconds": time.perf_counter() - started}
