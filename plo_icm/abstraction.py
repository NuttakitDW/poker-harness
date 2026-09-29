"""Explicit information abstraction and targeted-chance MCCFR for one PLO hand class."""

from __future__ import annotations

import itertools
import json
import math
import time
from collections import Counter

import numpy as np
from pokerkit import Card, OmahaHoldemHand

from .cards import SUITS, canonical_cards, deal
from .cards import parse_cards
from .game import PLOState
from .solver import Solver, _BudgetStop

RANK_VALUE = {rank: value for value, rank in enumerate("23456789TJQKA", 2)}


def suit_orbit(hand: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    made = set()
    for permutation in itertools.permutations(SUITS):
        mapping = dict(zip(SUITS, permutation))
        made.add(tuple(sorted(card[0] + mapping[card[1]] for card in hand)))
    return tuple(sorted(made))


def _valid_assignments(ranks: str, shape: str | None,
                       suited_group: tuple[str, ...]) -> list[tuple[str, ...]]:
    valid = []
    for suits in itertools.product(SUITS, repeat=4):
        cards = tuple(rank + suit for rank, suit in zip(ranks, suits))
        if len(set(cards)) != 4:
            continue
        counts = sorted(Counter(suits).values(), reverse=True)
        if shape == "double-suited" and counts != [2, 2]:
            continue
        if shape == "rainbow" and counts != [1, 1, 1, 1]:
            continue
        if shape == "single-suited":
            expected = sorted((len(suited_group), *(1 for _ in range(4 - len(suited_group)))),
                              reverse=True) if suited_group else [2, 1, 1]
            if counts != expected:
                continue
        if suited_group:
            available = list(enumerate(ranks))
            picked = []
            for rank in suited_group:
                match = next((item for item in available if item[1] == rank), None)
                if match is None:
                    break
                picked.append(match[0]); available.remove(match)
            if len(picked) != len(suited_group) or len({suits[i] for i in picked}) != 1:
                continue
            if any(i not in picked and suits[i] == suits[picked[0]] for i in range(4)):
                continue
        valid.append(cards)
    return valid


def resolve_hand(ranks: str, *, shape: str | None = None,
                 suited_group: tuple[str, ...] = (), exact: tuple[str, ...] = ()) -> tuple[str, ...]:
    if not isinstance(ranks, str) or len(ranks) != 4 or any(rank not in RANK_VALUE for rank in ranks):
        raise ValueError("name exactly four legal PLO ranks")
    if exact:
        try:
            return parse_cards(exact, count=4)
        except ValueError as exc:
            raise ValueError("name four distinct exact cards") from exc
    assignments = _valid_assignments(ranks, shape, suited_group)
    classes: dict[tuple[str, str], tuple[str, ...]] = {}
    for cards in assignments:
        classes.setdefault(canonical_cards(cards, ()), cards)
    if not classes:
        raise ValueError("suit description cannot form a physical PLO hand")
    if len(classes) != 1:
        raise ValueError("suit description has multiple inequivalent classes; give exact suits")
    cards = next(iter(classes.values()))
    distinct = []
    for suit in (card[1] for card in cards):
        if suit not in distinct:
            distinct.append(suit)
    names = ("s", "h") if shape == "double-suited" else ("s", "d", "h", "c")
    mapping = dict(zip(distinct, names))
    return tuple(card[0] + mapping[card[1]] for card in cards)


def preflop_bucket(hole: tuple[str, ...]) -> str:
    ranks = [card[0] for card in hole]
    values = sorted((RANK_VALUE[r] for r in ranks), reverse=True)
    multiplicity = tuple(sorted(Counter(ranks).values(), reverse=True))
    suit_counts = tuple(sorted(Counter(card[1] for card in hole).values(), reverse=True))
    unique = sorted(set(values), reverse=True)
    gaps = [a - b - 1 for a, b in zip(unique, unique[1:])]
    connectors = (sum(gap == 0 for gap in gaps), sum(gap == 1 for gap in gaps),
                  sum(gap >= 2 for gap in gaps))
    pair_band = tuple(sorted((2 if RANK_VALUE[rank] >= 10 else 1)
                             for rank, count in Counter(ranks).items() if count >= 2))
    return (f"m{multiplicity}|a{ranks.count('A')}|s{suit_counts}|"
            f"h{sum(v >= 10 for v in values)}|c{connectors}|p{pair_band}")


def observation_bucket(hole: tuple[str, ...], board: tuple[str, ...]) -> str:
    if not board:
        return preflop_bucket(hole)
    hand = OmahaHoldemHand.from_game(tuple(Card.parse("".join(hole))),
                                     tuple(Card.parse("".join(board))))
    board_ranks = Counter(card[0] for card in board)
    board_suits = Counter(card[1] for card in board)
    combined_suits = Counter(card[1] for card in hole + board)
    return (f"{preflop_bucket(hole)}|made:{hand.entry.label}|"
            f"bp:{tuple(sorted(board_ranks.values(), reverse=True))}|"
            f"bs:{tuple(sorted(board_suits.values(), reverse=True))}|"
            f"hs:{tuple(sorted(combined_suits.values(), reverse=True))}")


def abstract_key(state: PLOState, seat: int, hole: tuple[str, ...], board: tuple[str, ...],
                 focal_seat: int, focal_class: bool = False) -> str:
    shown_counts = (0, 3, 4, 5)
    observations = [observation_bucket(hole, board[:shown_counts[street]])
                    for street in range(state.street + 1)]
    payload = [seat, state.street, bool(seat == focal_seat and focal_class), observations, list(state.history),
               [round(x, 6) for x in state.behind], [round(x, 6) for x in state.street_put],
               sorted(state.folded)]
    return json.dumps(payload, separators=(",", ":"))


class AbstractSolver(Solver):
    """Six-seat solver sharing strategy across explicit card-feature buckets."""

    VERSION = "plo-abstract-v2"

    def __init__(self, config, *, focal_seat: int, focal_hand: tuple[str, ...],
                 target_lambda: float = .8):
        super().__init__(config)
        if isinstance(focal_seat, bool) or not isinstance(focal_seat, int) or focal_seat not in range(6):
            raise ValueError("focal_seat must be an integer from 0 through 5")
        if not isinstance(target_lambda, (int, float)) or isinstance(target_lambda, bool) \
                or not math.isfinite(target_lambda) or not 0 <= target_lambda < 1:
            raise ValueError("target_lambda must be finite and in [0, 1)")
        focal_hand = parse_cards(focal_hand, count=4)
        self.focal_seat = focal_seat
        self.focal_hand = tuple(focal_hand)
        self.orbit = suit_orbit(self.focal_hand)
        self._orbit_sets = {frozenset(hand) for hand in self.orbit}
        self.target_lambda = target_lambda

    def _key(self, state, seat, hole, board):
        focal_class = frozenset(hole) in self._orbit_sets
        return abstract_key(state, seat, hole, board, self.focal_seat, focal_class)

    def _target_deal(self):
        hand = self.orbit[self.rng.randrange(len(self.orbit))]
        remaining = [card for card in (r + s for r in "23456789TJQKA" for s in SUITS)
                     if card not in hand]
        self.rng.shuffle(remaining)
        holes = []
        cursor = 0
        for seat in range(6):
            if seat == self.focal_seat:
                holes.append(tuple(hand))
            else:
                holes.append(tuple(remaining[cursor:cursor + 4])); cursor += 4
        return tuple(holes), tuple(remaining[cursor:cursor + 5])

    def _mixture_deal(self):
        target = self.rng.random() < self.target_lambda
        holes, board = self._target_deal() if target else deal(self.rng)
        in_class = frozenset(holes[self.focal_seat]) in self._orbit_sets
        pclass = len(self.orbit) / math.comb(52, 4)
        weight = (1 / ((1 - self.target_lambda) + self.target_lambda / pclass)
                  if in_class else 1 / (1 - self.target_lambda))
        return holes, board, weight

    def train(self):
        self._began = time.perf_counter()
        self.stop_reason = "iterations"
        root = PLOState.new(self.config.stacks, sb=self.config.sb, bb=self.config.bb,
                            ante=self.config.ante, ante_mode=self.config.ante_mode,
                            opening_raise_mode=self.config.opening_raise_mode)
        try:
            for _ in range(self.config.iterations):
                holes, board, chance_weight = self._mixture_deal()
                for target in range(6):
                    regret_delta = {}
                    self._traverse(root, holes, board, target, regret_delta)
                    for key, delta in regret_delta.items():
                        self.infosets[key].regrets += chance_weight * delta
                        self.infosets[key].visits += 1
                    self.completed_traversals += 1
                average_delta = {}
                self._average_pass(root, holes, board, np.ones(6), 1., average_delta)
                for key, delta in average_delta.items():
                    self.infosets[key].strategy_sum += chance_weight * delta
                self.completed_iterations += 1
        except _BudgetStop:
            pass
        self.elapsed += time.perf_counter() - self._began
        return self.metadata()

    def metadata(self):
        result = super().metadata()
        result.update({"abstraction": self.VERSION, "targeted_chance_lambda": self.target_lambda,
                       "claim": "approximate abstract policy; not Nash or GTO"})
        return result
