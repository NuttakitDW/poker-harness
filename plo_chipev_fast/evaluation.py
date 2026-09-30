"""Fresh-deal evaluation of the frozen dense average policy."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from plo_chipev.evaluation import TIERS, action_label, hwang_tier, opportunity
from plo_chipev.game import PreflopState
from plo_chipev.showdown import precompute_ranks, settle_by_ranks
from plo_icm.cards import DECK, deal
from plo_icm.game import Action

from .trainer import FastTrainer

POSITION_NAMES = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
CARD_IDS = {card: index for index, card in enumerate(DECK)}


def _profile_hash(trainer: FastTrainer) -> str:
    digest = hashlib.sha256(b"plo-chipev-fast-frozen-average-v1")
    digest.update(trainer.model.strategy_sum.tobytes(order="C"))
    digest.update(str(trainer.completed_iterations).encode())
    digest.update((trainer.model.source_checkpoint_hash or "fresh").encode())
    return digest.hexdigest()


def _domain_seed(seed: int, profile_hash: str) -> int:
    material = json.dumps(
        ["plo-chipev-fast", "behavior-evaluation", seed, profile_hash],
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def _sample_index(rng: random.Random, probabilities: np.ndarray) -> int:
    point = rng.random()
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += float(probability)
        if point <= cumulative + 1e-15:
            return index
    return len(probabilities) - 1


def evaluate_profile(trainer: FastTrainer, *, hands: int, seed: int) -> dict[str, Any]:
    if isinstance(hands, bool) or not isinstance(hands, int) or hands <= 0:
        raise ValueError("hands must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    model = trainer.model
    profile_hash = _profile_hash(trainer)
    derived_seed = _domain_seed(seed, profile_hash)
    rng = random.Random(derived_seed)
    seat_vpip = np.zeros(6, dtype=np.int64)
    seat_net = np.zeros(6, dtype=np.float64)
    tier_population: Counter[str] = Counter()
    tier_vpip: Counter[str] = Counter()
    tier_opportunity: dict[str, Counter[str]] = defaultdict(Counter)
    tier_voluntary: dict[str, Counter[str]] = defaultdict(Counter)
    seat_opportunity: dict[str, Counter[str]] = defaultdict(Counter)
    seat_voluntary: dict[str, Counter[str]] = defaultdict(Counter)
    action_counts: dict[str, Counter[str]] = defaultdict(Counter)
    decisions = unseen = zero_weight = fallback = 0
    max_zero_sum_error = 0.0

    for _ in range(hands):
        holes, board = deal(rng)
        ranks = precompute_ranks(holes, board)
        hole_ids = tuple(tuple(CARD_IDS[card] for card in hole) for hole in holes)
        buckets = tuple(model.hands.bucket_for_cards(cards) for cards in hole_ids)
        tiers = tuple(hwang_tier(hole) for hole in holes)
        tier_population.update(tiers)
        voluntary = [False] * 6
        state = PreflopState.new()
        node = 0
        while not state.terminal:
            seat = state.actor
            assert seat is not None
            stage = opportunity(state)
            decision = int(model.tree.decision_index[node])
            count = int(model.tree.action_count[node])
            weights = model.strategy_sum[decision, buckets[seat], :count]
            weight = float(weights.sum())
            is_unseen = model.visits[decision, buckets[seat]] == 0
            probabilities = model.average_policy(node, buckets[seat])
            decisions += 1
            unseen += int(is_unseen)
            zero_weight += int(weight <= 0.0)
            fallback += int(weight <= 0.0)
            position = POSITION_NAMES[seat]
            seat_opportunity[position][stage] += 1
            tier_opportunity[tiers[seat]][stage] += 1
            choice = _sample_index(rng, probabilities)
            action = state.legal_actions()[choice]
            label = action_label(state, action)
            action_counts[stage][label] += 1
            if action in (Action.CALL, Action.POT):
                voluntary[seat] = True
                seat_voluntary[position][stage] += 1
                tier_voluntary[tiers[seat]][stage] += 1
            state = state.apply(action)
            node = int(model.tree.children[node, choice])
        if model.tree.histories[node] != state.history:
            raise RuntimeError("static tree diverged during evaluation")
        final = settle_by_ranks(
            state.base.behind,
            state.base.committed,
            state.base.folded,
            ranks,
            state.base.dead_money,
        )
        gains = np.asarray(final) - 100.0
        max_zero_sum_error = max(max_zero_sum_error, abs(float(gains.sum())))
        seat_net += gains
        for seat in range(6):
            seat_vpip[seat] += int(voluntary[seat])
            tier_vpip[tiers[seat]] += int(voluntary[seat])

    def opportunity_rows(
        opportunities: dict[str, Counter[str]], voluntary_counts: dict[str, Counter[str]], key: str
    ) -> dict[str, dict[str, float | int]]:
        return {
            stage: {
                "opportunities": count,
                "voluntary_actions": voluntary_counts[key][stage],
                "voluntary_rate": voluntary_counts[key][stage] / count,
            }
            for stage, count in sorted(opportunities[key].items())
        }

    return {
        "schema_version": 1,
        "evaluation": "fresh-deal simulation of frozen dense average strategy",
        "model_identity": {
            "profile_hash": profile_hash,
            "iterations_completed": trainer.completed_iterations,
            "source_checkpoint_hash": model.source_checkpoint_hash,
            "representation": "static-public-tree+dense-feature-buckets",
        },
        "rng": {
            "domain": "behavior-evaluation",
            "user_seed": seed,
            "derived_seed": derived_seed,
            "separate_from_training": True,
        },
        "table_hands": hands,
        "assumptions": {
            "variant": "PLO4 high",
            "format": "six-max tournament chip EV",
            "effective_stack_bb": 100.0,
            "blinds_bb": [0.5, 1.0],
            "ante_bb": 0.0,
            "rake": 0.0,
            "payouts_or_icm": False,
            "postflop": "forced check-down",
            "hand_abstraction": "572-feature buckets",
        },
        "claims": {
            "approximate_abstract_policy": True,
            "ordinary_plo_optimum": False,
            "gto_or_exploitability_certificate": False,
        },
        "by_seat": {
            POSITION_NAMES[seat]: {
                "vpip_count": int(seat_vpip[seat]),
                "vpip": float(seat_vpip[seat] / hands),
                "net_bb_per_100": float(100 * seat_net[seat] / hands),
                "by_opportunity": opportunity_rows(
                    seat_opportunity, seat_voluntary, POSITION_NAMES[seat]
                ),
            }
            for seat in range(6)
        },
        "by_tier": {
            tier: {
                "population": tier_population[tier],
                "vpip_count": tier_vpip[tier],
                "vpip": tier_vpip[tier] / tier_population[tier] if tier_population[tier] else None,
                "by_opportunity": opportunity_rows(tier_opportunity, tier_voluntary, tier),
            }
            for tier in TIERS
        },
        "actions_by_opportunity": {
            stage: dict(sorted(counts.items())) for stage, counts in sorted(action_counts.items())
        },
        "support": {
            "decisions": decisions,
            "unseen_decisions": unseen,
            "unseen_fraction": unseen / decisions,
            "zero_weight_decisions": zero_weight,
            "zero_weight_fraction": zero_weight / decisions,
            "uniform_fallback_decisions": fallback,
            "fallback_fraction": fallback / decisions,
        },
        "table_net_bb_per_100": float(100 * seat_net.sum() / hands),
        "maximum_table_zero_sum_error_bb": max_zero_sum_error,
    }

