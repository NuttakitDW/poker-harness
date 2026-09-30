#!/usr/bin/env python3
"""Census the existing Hwang-inspired PLO4 hand-tier classifier.

This is a hand-inventory analysis, not a solver and not a VPIP recommendation.
Every physical four-card combination has equal weight.
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))

import plo_type  # noqa: E402


RANKS = "AKQJT98765432"
SUITS = "shdc"
DECK = tuple(f"{rank}{suit}" for rank in RANKS for suit in SUITS)
RANK_PATTERN_LABELS = {
    (1, 1, 1, 1): "four_distinct_ranks",
    (2, 1, 1): "one_pair",
    (2, 2): "two_pair",
    (3, 1): "trips",
    (4,): "quads",
}

EDGE_CASES = (
    ("quads", "As Ah Ad Ac"),
    ("trips", "As Ah Ad Kc"),
    ("four_to_one_suit", "As Ks Qs Js"),
    ("three_to_one_suit", "As Ks Qs Jh"),
    ("double_suited", "As Ks Qh Jh"),
    ("rainbow", "As Kh Qd Jc"),
    ("ace_outside_suited_group", "As Kh Qh Jc"),
)


def physical_hands() -> Iterator[tuple[str, str, str, str]]:
    """Yield every unordered four-card hand from a standard 52-card deck once."""
    yield from itertools.combinations(DECK, 4)


def _percentage(count: int, total: int) -> float:
    return round(100 * count / total, 6)


def _sorted_counts(counter: collections.Counter[str], order: tuple[str, ...] = ()) -> dict[str, int]:
    keys = list(order) + sorted(set(counter) - set(order))
    return {key: counter[key] for key in keys if counter[key]}


def _classified(cards: tuple[str, ...]) -> tuple[plo_type.Hand, plo_type.Cluster]:
    hand = plo_type.read(" ".join(cards))
    if hand is None:  # Defensive: all generated hands contain four explicit physical cards.
        raise RuntimeError(f"classifier did not parse generated hand: {cards}")
    return hand, plo_type.classify(hand)


def census() -> dict[str, object]:
    """Return an exact, equally weighted census of the existing classifier."""
    tiers: collections.Counter[str] = collections.Counter()
    groups: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    forms: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    rank_patterns: collections.Counter[str] = collections.Counter()
    suit_shapes: collections.Counter[str] = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)

    total = 0
    for cards in physical_hands():
        hand, cluster = _classified(cards)
        total += 1
        tiers[cluster.tier] += 1
        groups[cluster.group][cluster.tier] += 1
        forms[cluster.form][cluster.tier] += 1
        pattern = tuple(sorted(collections.Counter(card[0] for card in cards).values(), reverse=True))
        rank_patterns[RANK_PATTERN_LABELS[pattern]] += 1
        shape = "double-suited" if hand.suiting.double else (
            "single-suited" if hand.suiting.suited else "rainbow")
        suit_shapes[shape] += 1
        if len(examples[cluster.tier]) < 5:
            examples[cluster.tier].append(" ".join(cards))

    expected = math.comb(52, 4)
    if total != expected:
        raise RuntimeError(f"incomplete census: counted {total}, expected {expected}")

    tier_rows = {
        tier: {
            "count": tiers[tier],
            "percent": _percentage(tiers[tier], total),
            "examples": examples[tier],
        }
        for tier in plo_type.TIERS
    }

    def breakdown(source: dict[str, collections.Counter[str]]) -> dict[str, object]:
        return {
            name: {
                "count": sum(counts.values()),
                "percent": _percentage(sum(counts.values()), total),
                "tiers": _sorted_counts(counts, plo_type.TIERS),
            }
            for name, counts in sorted(source.items())
        }

    edge_cases = {}
    for label, text in EDGE_CASES:
        hand = plo_type.read(text)
        if hand is None:
            raise RuntimeError(f"classifier did not parse edge case: {text}")
        cluster = plo_type.classify(hand)
        edge_cases[label] = {
            "cards": text,
            "group": cluster.group,
            "form": cluster.form,
            "tier": cluster.tier,
            "classifier_shape": "double-suited" if hand.suiting.double else (
                "single-suited" if hand.suiting.suited else "rainbow"),
            "ace_suited": hand.suiting.ace_suited,
        }

    premium_speculative = tiers[plo_type.PREMIUM] + tiers[plo_type.SPECULATIVE]
    premium_speculative_marginal = premium_speculative + tiers[plo_type.MARGINAL]
    return {
        "schema_version": 1,
        "analysis": "Exact physical-hand census of the existing authored Hwang-inspired classifier",
        "limitations": [
            "This classifier is an authored implementation inspired by Jeff Hwang chapter 4, not a verbatim exhaustive Hwang chart.",
            "Tier inventory is not VPIP, equilibrium strategy, action frequency, or evidence that a 30% VPIP is optimal.",
            "No solver, opponent model, position, action tree, equity, or rake calculation is used here.",
        ],
        "assumptions": {
            "variant": "four-card PLO high",
            "format": "six-max tournament chip EV; seats do not affect this inventory",
            "effective_stack_bb": 100,
            "starting_stacks": "six equal 100bb stacks",
            "ante": 0,
            "rake": 0,
            "tournament_payouts": "no payout or ICM adjustment (chip EV)",
            "weighting": "each unordered C(52,4) physical hole-card combination has weight 1",
        },
        "total_combinations": total,
        "tiers": tier_rows,
        "cumulative_tiers": {
            "premium_plus_speculative": {
                "count": premium_speculative,
                "percent": _percentage(premium_speculative, total),
            },
            "premium_plus_speculative_plus_marginal": {
                "count": premium_speculative_marginal,
                "percent": _percentage(premium_speculative_marginal, total),
            },
        },
        "rank_patterns": {
            name: {"count": count, "percent": _percentage(count, total)}
            for name, count in _sorted_counts(rank_patterns).items()
        },
        "classifier_suit_shapes": {
            name: {"count": count, "percent": _percentage(count, total)}
            for name, count in _sorted_counts(
                suit_shapes, ("double-suited", "single-suited", "rainbow")).items()
        },
        "groups": breakdown(groups),
        "forms": breakdown(forms),
        "edge_cases": edge_cases,
    }


def _summary(report: dict[str, object]) -> str:
    rows = ["Existing authored Hwang-inspired classifier (hand inventory, not VPIP):"]
    for tier, data in report["tiers"].items():
        rows.append(f"  {tier:<12} {data['count']:>6}  {data['percent']:>9.6f}%")
    combined = report["cumulative_tiers"]["premium_plus_speculative"]
    rows.append(f"  Premium + Speculative: {combined['count']} ({combined['percent']:.6f}%)")
    rows.append(f"  Total: {report['total_combinations']}")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the full JSON report to this path")
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    args = parser.parse_args()

    report = census()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered if args.json else _summary(report), end="" if args.json else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
