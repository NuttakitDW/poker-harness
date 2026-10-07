"""What each option was worth at a hero decision of a reviewed hand, in ICM equity.

Opponents' hands and the unseen board cards are dealt at random and each deal is weighted by how
likely the opponents were to take the hand's actual line with those cards (their average strategy at
every decision on the path). From the decision, each hero option is played out once per deal with every
player, the hero included, following the solve's average strategy; all options share the deal and the
random numbers, so their difference has little noise. Values are prize equity in big blinds of chips
(mtticm), turned into money with the field's prize pool per chip.
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

from plo_chipev_fast.trainer import _random_unit

from .fullkernels import _bucket, _reset_deal, _utility
from .kernels import _situation


@njit(cache=True)  # pragma: no cover - compiled native code
def _deal_rest(state: np.ndarray, hero: int, hero_cards: np.ndarray, known: np.ndarray, known_count: int,
               hands: np.ndarray, board: np.ndarray) -> None:
    deck = np.empty(52, dtype=np.int64)
    size = 0
    for card in range(52):
        taken = False
        for c in hero_cards:
            if c == card:
                taken = True
        for k in range(known_count):
            if known[k] == card:
                taken = True
        if not taken:
            deck[size] = card
            size += 1
    position = 0
    held = hands.shape[1]
    for seat in range(hands.shape[0]):
        for k in range(held):
            if seat == hero:
                hands[seat, k] = hero_cards[k]
                continue
            pick = position + int(_random_unit(state) * (size - position))
            if pick >= size:
                pick = size - 1
            deck[position], deck[pick] = deck[pick], deck[position]
            hands[seat, k] = deck[position]
            position += 1
    for k in range(5):
        if k < known_count:
            board[k] = known[k]
            continue
        pick = position + int(_random_unit(state) * (size - position))
        if pick >= size:
            pick = size - 1
        deck[position], deck[pick] = deck[pick], deck[position]
        board[k] = deck[position]
        position += 1


# boundscheck as in the training kernels' helpers: without it this parallel loop crashes (segfault)
@njit(parallel=True, boundscheck=True)  # pragma: no cover - compiled native code
def action_values(
    deals_per_thread: int, rng_states: np.ndarray, hero: int, hero_cards: np.ndarray, known: np.ndarray,
    known_count: int, decision: int, path_nodes: np.ndarray, path_slots: np.ndarray,
    policy: np.ndarray, bucket_of: np.ndarray, rank5: np.ndarray, comb: np.ndarray, actor: np.ndarray,
    street: np.ndarray, decision_index: np.ndarray, row_start: np.ndarray, children: np.ndarray,
    action_count: np.ndarray, behind: np.ndarray, sidepot_count: np.ndarray, sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray, stacks: np.ndarray, payouts: np.ndarray, outcome_start: np.ndarray,
    outcome_winners: np.ndarray, outcome_values: np.ndarray,
) -> np.ndarray:
    """Per thread: (weight sum, weighted value of each option (3 columns), weight squared sum)."""
    seats = behind.shape[1]
    threads = rng_states.size
    out = np.zeros((threads, 5))
    for thread in prange(threads):
        state = rng_states[thread:thread + 1]
        hands = np.empty((seats, hero_cards.size), dtype=np.int64)
        board = np.empty(5, dtype=np.int64)
        preflop = np.empty(seats, dtype=np.int64)
        ranks = np.empty(seats, dtype=np.int64)
        buckets = np.empty((4, seats), dtype=np.int64)
        distributions = np.empty((4, 1176), dtype=np.int64)
        counts = np.zeros(4, dtype=np.int64)
        scratch = np.empty(seats + 2 * (1 << seats), dtype=np.float64)  # fullkernels.scratch_size
        options = action_count[decision]
        for _ in range(deals_per_thread):
            _deal_rest(state, hero, hero_cards, known, known_count, hands, board)
            _situation(hands, board, bucket_of, rank5, comb, preflop, ranks)
            _reset_deal(buckets, counts, preflop)
            weight = 1.0
            for i in range(path_nodes.size):
                node = path_nodes[i]
                seat = actor[node]
                if seat == hero:
                    continue
                b = _bucket(street[node], seat, hands, board, buckets, distributions, counts, rank5, comb)
                weight *= policy[row_start[decision_index[node]] + b, path_slots[i]]
                if weight <= 0.0:
                    break
            if weight <= 0.0:
                continue
            saved = state[0]
            out[thread, 0] += weight
            out[thread, 4] += weight * weight
            for option in range(options):
                state[0] = saved  # the same random numbers for every option
                node = children[decision, option]
                while actor[node] >= 0:
                    seat = actor[node]
                    b = _bucket(street[node], seat, hands, board, buckets, distributions, counts, rank5, comb)
                    row = row_start[decision_index[node]] + b
                    count = action_count[node]
                    point = _random_unit(state)
                    choice = count - 1
                    acc = 0.0
                    for s in range(count):
                        acc += policy[row, s]
                        if point <= acc:
                            choice = s
                            break
                    node = children[node, choice]
                value = _utility(node, hero, stacks, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
                                 ranks, payouts, scratch, outcome_start, outcome_winners, outcome_values)
                out[thread, 1 + option] += weight * value
    return out
