"""Rank estimates and CSV exports for complete PLO4 suit-class samples."""

from __future__ import annotations

import csv
import itertools
import math
import pathlib
from collections.abc import Mapping

from .cache import Metadata
from .cards import PHYSICAL_HANDS, SUIT_CLASSES, card_text, class_key, enumerate_classes
from .simulation import TrialStats


def ranked_classes(rows: Mapping[str, TrialStats]) -> list[dict]:
    classes = enumerate_classes()
    if set(rows) != {hand.key for hand in classes}:
        missing = len(classes) - sum(hand.key in rows for hand in classes)
        raise ValueError(f"ranking requires all {SUIT_CLASSES:,} classes; missing {missing:,}")
    if any(rows[hand.key].n < 2 or not math.isfinite(rows[hand.key].standard_error)
           for hand in classes):
        raise ValueError("ranking requires at least two valid trials per class")
    ordered = sorted(classes, key=lambda hand: (-rows[hand.key].equity, hand.key))
    output: list[dict] = []
    stronger = 0
    for _, equal_group in itertools.groupby(ordered, key=lambda hand: rows[hand.key].equity):
        group = list(equal_group)
        group_multiplicity = sum(hand.multiplicity for hand in group)
        below = PHYSICAL_HANDS - stronger - group_multiplicity
        class_start = len(output) + 1
        class_end = len(output) + len(group)
        for hand in group:
            stats = rows[hand.key]
            se = stats.standard_error
            output.append({
                "class_key": hand.key, "representative": hand.text,
                "multiplicity": hand.multiplicity, "samples": stats.n,
                "equity": stats.equity, "equity_standard_error": se,
                "equity_ci95_low": max(0.0, stats.equity - 1.96 * se),
                "equity_ci95_high": min(1.0, stats.equity + 1.96 * se),
                "win_rate": stats.win_rate, "tie_rate": stats.tie_rate,
                "estimated_class_rank": (class_start + class_end) / 2,
                "estimated_class_rank_start": class_start,
                "estimated_class_rank_end": class_end,
                "estimated_physical_rank_start": stronger + 1,
                "estimated_physical_rank_end": stronger + group_multiplicity,
                "physical_weighted_percentile": 100 * (below + group_multiplicity / 2) / PHYSICAL_HANDS,
                "rank_label": "Monte Carlo estimate; ordering uncertainty is not included in equity CI",
            })
        stronger += group_multiplicity
    return output


def _write(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def export_tables(rows: Mapping[str, TrialStats], class_csv: pathlib.Path,
                  physical_csv: pathlib.Path, metadata: Metadata) -> None:
    ranked = ranked_classes(rows)
    provenance = {"global_seed": metadata.global_seed, "opponents": metadata.opponents,
                  "opponent_range": metadata.opponent_range, "evaluator": metadata.evaluator,
                  "rng": metadata.rng, "python_runtime": metadata.python_runtime,
                  "source_fingerprint": metadata.source_fingerprint}
    ranked = [{**row, **provenance} for row in ranked]
    _write(class_csv, ranked)
    by_key = {row["class_key"]: row for row in ranked}
    physical = []
    for hand in itertools.combinations(range(52), 4):
        row = by_key[class_key(hand)]
        physical.append({
            "physical_hand": card_text(hand), "class_key": row["class_key"],
            "class_representative": row["representative"],
            "class_multiplicity": row["multiplicity"], "samples": row["samples"],
            "equity": row["equity"], "equity_standard_error": row["equity_standard_error"],
            "equity_ci95_low": row["equity_ci95_low"], "equity_ci95_high": row["equity_ci95_high"],
            "estimated_class_rank": row["estimated_class_rank"],
            "estimated_physical_rank_start": row["estimated_physical_rank_start"],
            "estimated_physical_rank_end": row["estimated_physical_rank_end"],
            "physical_weighted_percentile": row["physical_weighted_percentile"],
            "rank_label": row["rank_label"],
            **provenance,
        })
    physical.sort(key=lambda row: (row["estimated_class_rank"], row["physical_hand"]))
    _write(physical_csv, physical)


def weighted_summary(rows: Mapping[str, TrialStats]) -> dict[str, float]:
    classes = enumerate_classes()
    if any(hand.key not in rows for hand in classes):
        raise ValueError("weighted summary requires every suit class")
    weighted_equity = sum(hand.multiplicity * rows[hand.key].equity for hand in classes) / PHYSICAL_HANDS
    propagated = math.sqrt(sum((hand.multiplicity / PHYSICAL_HANDS
                                * rows[hand.key].standard_error) ** 2 for hand in classes))
    return {"weighted_equity": weighted_equity,
            "propagated_standard_error": propagated,
            "physical_hands": PHYSICAL_HANDS,
            "suit_classes": SUIT_CLASSES}
