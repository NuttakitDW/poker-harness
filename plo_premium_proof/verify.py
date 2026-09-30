"""Exact-hand best-response audit of first-in folds against a solved profile."""

from __future__ import annotations

import dataclasses
import math
import random
import time
from pathlib import Path
from typing import Any

import numba
import numpy as np

from plo_chipev.evaluation import _plo_type
from plo_chipev_fast.tree import ACTION_NAMES

from .kernels import BATCH, best_response_tasks, tree_links
from .solve import load_model, thread_seeds
from .tables import (
    FIRST_IN_POSITIONS,
    HandClass,
    HandTables,
    TreeArrays,
    colex_index,
    comb_table,
    five_card_ranks,
    hand_classes,
    select_classes,
)

ROOT_LABELS = {"fold": "fold", "call": "limp", "pot": "pot_open"}
Z_CRITICAL = 3.0  # |z| >= 3: roughly 1-in-740 two-sided false alarm per test
PRUNE = 1e-9


def average_policy(strategy_sum: np.ndarray, tree: TreeArrays) -> np.ndarray:
    """Normalized average strategy; unreached rows fall back to uniform over legal."""
    totals = strategy_sum.sum(axis=2, keepdims=True)
    policy = np.divide(strategy_sum, totals, out=np.zeros_like(strategy_sum), where=totals > 0)
    counts = tree.action_count[tree.actor >= 0].astype(np.int64)
    legal = np.arange(3)[None, :] < counts[:, None]
    uniform = legal / counts[:, None]
    empty = totals[..., 0] <= 0
    policy[empty] = np.broadcast_to(uniform[:, None, :], policy.shape)[empty]
    policy[~np.broadcast_to(legal[:, None, :], policy.shape)] = 0.0
    return policy


def hwang_form(hand: HandClass) -> str:
    classifier = _plo_type()
    text = " ".join(hand.text[i:i + 2] for i in range(0, 8, 2))
    return classifier.classify(classifier.read(text)).form


@dataclasses.dataclass(frozen=True)
class Estimate:
    mean: float
    se: float


def _ratio(sum_y: float, sum_y2: float, sum_yz: float, sum_z: float, sum_z2: float) -> Estimate:
    """Ratio estimator sum(y)/sum(z) with a delta-method standard error."""
    if sum_z <= 0:
        return Estimate(math.nan, math.inf)
    mean = sum_y / sum_z
    residual = max(sum_y2 - 2 * mean * sum_yz + mean * mean * sum_z2, 0.0)
    return Estimate(mean, math.sqrt(residual) / sum_z)


def root_labels(tree: TreeArrays, seat: int) -> list[str]:
    root = int(tree.first_in_nodes[seat])
    count = int(tree.action_count[root])
    return [ROOT_LABELS[ACTION_NAMES[int(a)]] for a in tree.action_ids[root, :count]]


def verdict(labels: list[str], crossfit: list[Estimate], optimistic: list[float]) -> str:
    fold = crossfit[labels.index("fold")].mean
    others = [i for i, label in enumerate(labels) if label != "fold"]
    if any(crossfit[i].mean - Z_CRITICAL * crossfit[i].se > fold for i in others):
        return "must_not_fold"
    if all(crossfit[i].mean + Z_CRITICAL * crossfit[i].se < fold and optimistic[i] < fold
           for i in others):
        return "fold_is_best_response"
    return "inconclusive"


def run_tasks(
    classes: list[HandClass],
    seats: list[int],
    *,
    policy: np.ndarray,
    tables: HandTables,
    tree: TreeArrays,
    rank5: np.ndarray,
    comb: np.ndarray,
    fit_samples: int,
    test_samples: int,
    seed: int,
    with_profile: bool = False,
) -> list[dict[str, Any]]:
    pairs = [(hand, seat) for hand in classes for seat in seats]
    cards = np.asarray([hand.cards for hand, _ in pairs], dtype=np.int64)
    seat_array = np.asarray([seat for _, seat in pairs], dtype=np.int64)
    seeds = thread_seeds(seed, len(pairs))
    fold_slot = np.asarray(
        [int(np.flatnonzero(tree.action_ids[node] == 0)[0]) for node in tree.first_in_nodes],
        dtype=np.int64,
    )
    parent, parent_slot, subtree_end = tree_links(tree.children, tree.action_count, tree.actor)
    optimistic = np.zeros((len(pairs), 3))
    moments = np.zeros((len(pairs), 4, 6))
    best_response_tasks(
        cards, seat_array, seeds, -(-fit_samples // BATCH), -(-test_samples // BATCH),
        with_profile, tree.first_in_nodes, fold_slot, parent, parent_slot, subtree_end,
        tables.bucket_of, rank5, comb, policy, tree.actor, tree.decision_index, tree.children,
        tree.action_count, tree.behind, tree.sidepot_count, tree.sidepot_amount,
        tree.sidepot_eligible_mask, PRUNE, optimistic, moments,
    )
    rows = []
    for index, (hand, seat) in enumerate(pairs):
        labels = root_labels(tree, seat)
        sum_z, sum_z2 = moments[index, 3, 0], moments[index, 3, 1]
        crossfit = [_ratio(*moments[index, a, 0:3], sum_z, sum_z2) for a in range(len(labels))]
        profile = [_ratio(*moments[index, a, 3:6], sum_z, sum_z2) for a in range(len(labels))]
        root = int(tree.first_in_nodes[seat])
        bucket = int(tables.bucket_of[colex_index(hand.cards)])
        mix = policy[int(tree.decision_index[root]), bucket, :len(labels)]
        rows.append({
            "hand": hand.text,
            "combos": hand.combos,
            "tier": hand.tier,
            "position": FIRST_IN_POSITIONS[seat],
            "actions": labels,
            "solver_frequency": dict(zip(labels, map(float, mix))),
            "ev_best_response": {l: e.mean for l, e in zip(labels, crossfit)},
            "se_best_response": {l: e.se for l, e in zip(labels, crossfit)},
            "ev_in_sample_upper": dict(zip(labels, map(float, optimistic[index, :len(labels)]))),
            **({
                "ev_following_profile": {l: e.mean for l, e in zip(labels, profile)},
                "profile_value": float(sum(p * e.mean for p, e in zip(mix, profile))),
            } if with_profile else {}),
            "verdict": verdict(labels, crossfit, list(optimistic[index, :len(labels)])),
        })
    return rows


def _weighted_mean(rows: list[dict[str, Any]], value) -> float:
    total = sum(row["combos"] for row in rows)
    return sum(row["combos"] * value(row) for row in rows) / total if total else math.nan


def summarize(rows: list[dict[str, Any]], exploit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_position: dict[str, Any] = {}
    for position in FIRST_IN_POSITIONS:
        subset = [row for row in rows if row["position"] == position]
        if not subset:
            continue
        counts = {name: 0 for name in ("must_not_fold", "fold_is_best_response", "inconclusive")}
        combos = dict.fromkeys(counts, 0)
        for row in subset:
            counts[row["verdict"]] += 1
            combos[row["verdict"]] += row["combos"]
        folds = sorted(
            (row for row in subset if row["verdict"] != "must_not_fold"),
            key=lambda row: max(v for k, v in row["ev_best_response"].items() if k != "fold")
            - row["ev_best_response"]["fold"],
        )
        by_position[position] = {
            "classes": len(subset),
            "combos": sum(row["combos"] for row in subset),
            "verdict_classes": counts,
            "verdict_combos": combos,
            "solver_premium_fold_frequency": _weighted_mean(
                subset, lambda row: row["solver_frequency"]["fold"]),
            "not_proven_open": [
                {
                    "hand": row["hand"],
                    "form": row.get("form"),
                    "verdict": row["verdict"],
                    "ev": row["ev_best_response"],
                    "se": row["se_best_response"],
                }
                for row in folds
            ],
        }
    exploit: dict[str, Any] = {}
    for position in FIRST_IN_POSITIONS:
        subset = [row for row in exploit_rows if row["position"] == position]
        if subset:
            exploit[position] = {
                "classes": len(subset),
                "mean_best_response_gain_bb": _weighted_mean(
                    subset, lambda row: max(row["ev_best_response"].values()) - row["profile_value"]),
            }
    return {"premium_first_in": by_position, "profile_gap_all_tiers": exploit}


def verify(
    model: Path,
    *,
    fit_samples: int,
    test_samples: int,
    threads: int,
    seed: int,
    positions: tuple[str, ...] = FIRST_IN_POSITIONS,
    limit: int | None = None,
    exploit_classes: int = 0,
    tier: str = "Premium",
    per_tier: int | None = None,
    log=print,
) -> dict[str, Any]:
    started = time.perf_counter()
    _, strategy_sum, meta = load_model(model)
    tables = HandTables.build()
    tree = TreeArrays.build()
    if strategy_sum.shape != (tree.decision_count, tables.bucket_count, 3):
        raise ValueError("checkpoint shape does not match the tier-pure abstraction")
    policy = average_policy(strategy_sum, tree)
    rank5 = five_card_ranks()
    comb = comb_table()
    numba.set_num_threads(threads)
    seats = [FIRST_IN_POSITIONS.index(name) for name in positions]
    premium, weights = select_classes(tables, tier, per_tier=per_tier, limit=limit, seed=seed)
    common = dict(policy=policy, tables=tables, tree=tree, rank5=rank5, comb=comb,
                  fit_samples=fit_samples, test_samples=test_samples)
    log(f"premium classes: {len(premium)} x seats {positions}")
    rows = run_tasks(premium, seats, seed=seed, **common)
    for row, (hand, weight) in zip(rows, [(h, w) for h, w in zip(premium, weights) for _ in seats]):
        row["form"] = hwang_form(hand)
        row["sample_weight"] = weight
    exploit_rows: list[dict[str, Any]] = []
    if exploit_classes:
        everyone = list(hand_classes(tables))
        picked = random.Random(seed).sample(everyone, min(exploit_classes, len(everyone)))
        log(f"profile-gap classes (all tiers): {len(picked)}")
        exploit_rows = run_tasks(picked, seats, seed=seed + 1, with_profile=True, **common)
    return {
        "schema": "plo-premium-proof-report-v1",
        "tier": tier,
        "per_tier": per_tier,
        "model": str(model),
        "model_meta": meta,
        "samples": {"fit": fit_samples, "test": test_samples},
        "decision_rule": {
            "must_not_fold": f"cross-fitted BR EV of limp or pot open exceeds fold by >= {Z_CRITICAL} SE",
            "fold_is_best_response": f"every non-fold action is below fold by >= {Z_CRITICAL} SE "
                                     "and also below fold in-sample (upward-biased)",
        },
        "summary": summarize(rows, exploit_rows),
        "premium_rows": rows,
        "profile_gap_rows": exploit_rows,
        "seconds": time.perf_counter() - started,
    }
