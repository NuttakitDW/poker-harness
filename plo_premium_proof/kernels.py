"""Numba kernels: PLO showdown ranks, external-sampling MCCFR, and best response."""

from __future__ import annotations

import numpy as np
from numba import njit, prange

from plo_chipev_fast.trainer import _probabilities, _random_unit, _terminal_target_utility

NO_CARD = -1
# Numba cannot reload cached recursive functions (segfaults on the second process),
# so the recursive kernels and their parallel drivers are compiled fresh each run.


@njit(cache=True)  # pragma: no cover - compiled native code
def _sort_small(cards: np.ndarray, count: int) -> None:
    for i in range(1, count):
        value = cards[i]
        j = i - 1
        while j >= 0 and cards[j] > value:
            cards[j + 1] = cards[j]
            j -= 1
        cards[j + 1] = value


@njit(cache=True)  # pragma: no cover - compiled native code
def colex(cards: np.ndarray, count: int, comb: np.ndarray) -> int:
    scratch = np.empty(5, dtype=np.int64)
    for i in range(count):
        scratch[i] = cards[i]
    _sort_small(scratch, count)
    index = 0
    for i in range(count):
        index += comb[scratch[i], i + 1]
    return index


@njit(cache=True)  # pragma: no cover - compiled native code
def plo_rank(hole: np.ndarray, board: np.ndarray, rank5: np.ndarray, comb: np.ndarray) -> int:
    """Best Omaha high rank (exactly two hole + three board cards, four or five hole cards); lower wins."""
    best = 1 << 30
    five = np.empty(5, dtype=np.int64)
    held = hole.shape[0]
    for i in range(held):
        for j in range(i + 1, held):
            for x in range(5):
                for y in range(x + 1, 5):
                    for z in range(y + 1, 5):
                        five[0] = hole[i]
                        five[1] = hole[j]
                        five[2] = board[x]
                        five[3] = board[y]
                        five[4] = board[z]
                        rank = rank5[colex(five, 5, comb)]
                        if rank < best:
                            best = rank
    return best


@njit(cache=True)  # pragma: no cover - compiled native code
def _deal(
    state: np.ndarray, hero: int, hero_cards: np.ndarray, hands: np.ndarray, board: np.ndarray
) -> None:
    """Deal every non-hero seat (``hands`` has one row per seat) and the board; ``hero < 0`` deals all."""
    deck = np.empty(52, dtype=np.int64)
    size = 0
    for card in range(52):
        taken = False
        if hero >= 0:
            for k in range(hero_cards.shape[0]):
                if hero_cards[k] == card:
                    taken = True
        if not taken:
            deck[size] = card
            size += 1
    position = 0
    for seat in range(hands.shape[0]):
        for k in range(hands.shape[1]):
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
        pick = position + int(_random_unit(state) * (size - position))
        if pick >= size:
            pick = size - 1
        deck[position], deck[pick] = deck[pick], deck[position]
        board[k] = deck[position]
        position += 1


@njit(cache=True)  # pragma: no cover - compiled native code
def _situation(
    hands: np.ndarray,
    board: np.ndarray,
    bucket_of: np.ndarray,
    rank5: np.ndarray,
    comb: np.ndarray,
    buckets: np.ndarray,
    ranks: np.ndarray,
) -> None:
    for seat in range(hands.shape[0]):
        buckets[seat] = bucket_of[colex(hands[seat], hands.shape[1], comb)]
        ranks[seat] = plo_rank(hands[seat], board, rank5, comb)


@njit()  # pragma: no cover - compiled native code
def _traverse(
    node: int,
    traverser: int,
    buckets: np.ndarray,
    ranks: np.ndarray,
    actor: np.ndarray,
    decision_index: np.ndarray,
    children: np.ndarray,
    action_count: np.ndarray,
    behind: np.ndarray,
    sidepot_count: np.ndarray,
    sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray,
    regrets: np.ndarray,
    strategy_sum: np.ndarray,
    average_weight: float,
    state: np.ndarray,
) -> float:
    seat = actor[node]
    if seat < 0:
        return _terminal_target_utility(
            node, traverser, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask, ranks
        )
    decision = decision_index[node]
    bucket = buckets[seat]
    count = action_count[node]
    p0, p1, p2 = _probabilities(regrets, decision, bucket, count)
    if seat == traverser:
        v0 = _traverse(
            children[node, 0], traverser, buckets, ranks, actor, decision_index, children,
            action_count, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
            regrets, strategy_sum, average_weight, state,
        )
        v1 = 0.0
        v2 = 0.0
        if count > 1:
            v1 = _traverse(
                children[node, 1], traverser, buckets, ranks, actor, decision_index, children,
                action_count, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
                regrets, strategy_sum, average_weight, state,
            )
        if count > 2:
            v2 = _traverse(
                children[node, 2], traverser, buckets, ranks, actor, decision_index, children,
                action_count, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
                regrets, strategy_sum, average_weight, state,
            )
        expected = p0 * v0 + p1 * v1 + p2 * v2
        regrets[decision, bucket, 0] += v0 - expected
        if count > 1:
            regrets[decision, bucket, 1] += v1 - expected
        if count > 2:
            regrets[decision, bucket, 2] += v2 - expected
        return expected
    # Opponent node: on-policy sample, and credit the average strategy here
    # (standard external-sampling "simple averaging").
    strategy_sum[decision, bucket, 0] += average_weight * p0
    if count > 1:
        strategy_sum[decision, bucket, 1] += average_weight * p1
    if count > 2:
        strategy_sum[decision, bucket, 2] += average_weight * p2
    point = _random_unit(state)
    choice = 0
    if point > p0:
        choice = 1 if (count == 2 or point <= p0 + p1) else 2
    return _traverse(
        children[node, choice], traverser, buckets, ranks, actor, decision_index, children,
        action_count, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
        regrets, strategy_sum, average_weight, state,
    )


@njit(parallel=True)  # pragma: no cover - compiled native code
def train_batch(
    traversals_per_thread: int,
    rng_states: np.ndarray,
    average_weight: float,
    bucket_of: np.ndarray,
    rank5: np.ndarray,
    comb: np.ndarray,
    actor: np.ndarray,
    decision_index: np.ndarray,
    children: np.ndarray,
    action_count: np.ndarray,
    behind: np.ndarray,
    sidepot_count: np.ndarray,
    sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray,
    regrets: np.ndarray,
    strategy_sum: np.ndarray,
) -> None:
    """Hogwild MCCFR: each thread runs its own fresh deals into shared tables."""
    threads = rng_states.size
    for thread in prange(threads):
        state = rng_states[thread:thread + 1]
        hands = np.empty((6, 4), dtype=np.int64)
        board = np.empty(5, dtype=np.int64)
        buckets = np.empty(6, dtype=np.int64)
        ranks = np.empty(6, dtype=np.int64)
        none = np.empty(4, dtype=np.int64)
        for step in range(traversals_per_thread):
            _deal(state, -1, none, hands, board)
            _situation(hands, board, bucket_of, rank5, comb, buckets, ranks)
            _traverse(
                0, step % 6, buckets, ranks, actor, decision_index, children, action_count,
                behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
                regrets, strategy_sum, average_weight, state,
            )


@njit(cache=True)  # pragma: no cover - compiled native code
def best_response_choices(
    root: int, hero: int, weighted: np.ndarray, actor: np.ndarray, children: np.ndarray,
    action_count: np.ndarray, values: np.ndarray, choice: np.ndarray,
) -> None:
    """Backward induction: max at hero nodes, sum at opponent nodes (reach is in W)."""
    # Public nodes are numbered in preorder, so every child index exceeds its parent's.
    for node in range(actor.size - 1, root - 1, -1):
        seat = actor[node]
        if seat < 0:
            values[node] = weighted[node]
            continue
        count = action_count[node]
        if seat == hero:
            best = children[node, 0]
            slot = 0
            for action in range(1, count):
                if values[children[node, action]] > values[best]:
                    best = children[node, action]
                    slot = action
            values[node] = values[best]
            choice[node] = slot
        else:
            total = 0.0
            for action in range(count):
                total += values[children[node, action]]
            values[node] = total




BATCH = 64
FULL, BEST_RESPONSE, PROFILE = 0, 1, 2


@njit(cache=True)  # pragma: no cover - compiled native code
def tree_links(children: np.ndarray, action_count: np.ndarray, actor: np.ndarray):
    """Parent, parent action slot, and last preorder index of every subtree."""
    nodes = actor.size
    parent = np.full(nodes, -1, dtype=np.int64)
    slot = np.zeros(nodes, dtype=np.int64)
    end = np.arange(nodes).astype(np.int64)
    for node in range(nodes):
        if actor[node] >= 0:
            for action in range(action_count[node]):
                parent[children[node, action]] = node
                slot[children[node, action]] = action
    for node in range(nodes - 1, -1, -1):
        if actor[node] >= 0:
            end[node] = end[children[node, action_count[node] - 1]]
    return parent, slot, end


@njit(cache=True)  # pragma: no cover - compiled native code
def _fill_batch(
    state: np.ndarray, hero: int, hero_cards: np.ndarray, first_in_nodes: np.ndarray,
    fold_slot: np.ndarray, bucket_of: np.ndarray, rank5: np.ndarray, comb: np.ndarray,
    average: np.ndarray, decision_index: np.ndarray, buckets: np.ndarray, ranks: np.ndarray,
    prefix: np.ndarray,
) -> None:
    """Deal a batch; ``prefix`` is the chance every earlier seat folded to hero."""
    hands = np.empty((6, 4), dtype=np.int64)
    board = np.empty(5, dtype=np.int64)
    for k in range(buckets.shape[0]):
        _deal(state, hero, hero_cards, hands, board)
        _situation(hands, board, bucket_of, rank5, comb, buckets[k], ranks[k])
        reach = 1.0
        for seat in range(hero):
            reach *= average[decision_index[first_in_nodes[seat]], buckets[k, seat], fold_slot[seat]]
        prefix[k] = reach


@njit(cache=True)  # pragma: no cover - compiled native code
def _propagate(
    mode: int, hero: int, root: int, end: int, parent: np.ndarray, parent_slot: np.ndarray,
    root_action: np.ndarray, choice: np.ndarray, prefix: np.ndarray, buckets: np.ndarray,
    ranks: np.ndarray, average: np.ndarray, actor: np.ndarray, decision_index: np.ndarray,
    behind: np.ndarray, sidepot_count: np.ndarray, sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray, prune: float, reach: np.ndarray,
    weighted: np.ndarray, per_sample: np.ndarray,
) -> None:
    """Push a batch of opponent reaches down the subtree in preorder.

    FULL keeps every hero branch (for backward induction into ``weighted``);
    BEST_RESPONSE follows ``choice`` below the root and PROFILE follows hero's
    own average strategy, both adding terminal utility into ``per_sample[root
    action, k]``. Every root action is always expanded.
    """
    size = prefix.size
    for k in range(size):
        reach[root, k] = prefix[k]
    for node in range(root + 1, end + 1):
        up = parent[node]
        slot = parent_slot[node]
        seat = actor[up]
        decision = decision_index[up]
        live = False
        for k in range(size):
            above = reach[up, k]
            if above <= prune:
                reach[node, k] = 0.0
                continue
            if seat != hero:
                factor = average[decision, buckets[k, seat], slot]
            elif up == root or mode == FULL:
                factor = 1.0
            elif mode == BEST_RESPONSE:
                factor = 1.0 if choice[up] == slot else 0.0
            else:
                factor = average[decision, buckets[k, hero], slot]
            value = above * factor
            reach[node, k] = value
            if value > prune:
                live = True
        if actor[node] >= 0 or not live:
            continue
        for k in range(size):
            value = reach[node, k]
            if value <= prune:
                continue
            utility = value * _terminal_target_utility(
                node, hero, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask, ranks[k]
            )
            if mode == FULL:
                weighted[node] += utility
            else:
                per_sample[root_action[node], k] += utility


@njit(parallel=True)  # pragma: no cover - compiled native code
def best_response_tasks(
    task_cards: np.ndarray,
    task_seat: np.ndarray,
    task_seed: np.ndarray,
    fit_batches: int,
    test_batches: int,
    with_profile: bool,
    first_in_nodes: np.ndarray,
    fold_slot: np.ndarray,
    parent: np.ndarray,
    parent_slot: np.ndarray,
    subtree_end: np.ndarray,
    bucket_of: np.ndarray,
    rank5: np.ndarray,
    comb: np.ndarray,
    average: np.ndarray,
    actor: np.ndarray,
    decision_index: np.ndarray,
    children: np.ndarray,
    action_count: np.ndarray,
    behind: np.ndarray,
    sidepot_count: np.ndarray,
    sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray,
    prune: float,
    optimistic: np.ndarray,
    moments: np.ndarray,
) -> None:
    """Cross-fitted best response for a fixed hero hand at its first-in node.

    Fit batches choose hero's continuation (max over later decisions); independent
    test batches then evaluate each root action under that continuation, an
    unbiased estimate of a valid strategy's value (so a lower bound on the BR).

    ``optimistic[t, a]``: in-sample BR value on the fit half (biased upward).
    ``moments[t, a, :]``: sums of y_br, y_br^2, y_br*z, y_prof, y_prof^2, y_prof*z
    per root action ``a``; ``moments[t, 3, :2]`` holds sum z and sum z^2.
    """
    nodes = actor.size
    for task in prange(task_cards.shape[0]):
        hero = task_seat[task]
        root = first_in_nodes[hero]
        end = subtree_end[root]
        state = task_seed[task:task + 1].copy()
        hero_cards = task_cards[task]
        buckets = np.empty((BATCH, 6), dtype=np.int64)
        ranks = np.empty((BATCH, 6), dtype=np.int64)
        prefix = np.empty(BATCH, dtype=np.float64)
        reach = np.zeros((nodes, BATCH), dtype=np.float64)
        weighted = np.zeros(nodes, dtype=np.float64)
        values = np.zeros(nodes, dtype=np.float64)
        choice = np.zeros(nodes, dtype=np.int64)
        per_sample = np.zeros((3, BATCH), dtype=np.float64)
        root_action = np.zeros(nodes, dtype=np.int64)
        for node in range(root + 1, end + 1):
            up = parent[node]
            root_action[node] = parent_slot[node] if up == root else root_action[up]
        fit_reach = 0.0
        for _ in range(fit_batches):
            _fill_batch(state, hero, hero_cards, first_in_nodes, fold_slot, bucket_of, rank5,
                        comb, average, decision_index, buckets, ranks, prefix)
            fit_reach += prefix.sum()
            _propagate(FULL, hero, root, end, parent, parent_slot, root_action, choice, prefix,
                       buckets, ranks, average, actor, decision_index, behind, sidepot_count,
                       sidepot_amount, sidepot_eligible_mask, prune, reach, weighted, per_sample)
        best_response_choices(root, hero, weighted, actor, children, action_count, values, choice)
        count = action_count[root]
        for action in range(count):
            optimistic[task, action] = values[children[root, action]] / fit_reach
        modes = 2 if with_profile else 1
        for _ in range(test_batches):
            _fill_batch(state, hero, hero_cards, first_in_nodes, fold_slot, bucket_of, rank5,
                        comb, average, decision_index, buckets, ranks, prefix)
            for k in range(BATCH):
                moments[task, 3, 0] += prefix[k]
                moments[task, 3, 1] += prefix[k] * prefix[k]
            for pass_index in range(modes):
                per_sample[:, :] = 0.0
                _propagate(BEST_RESPONSE if pass_index == 0 else PROFILE, hero, root, end,
                           parent, parent_slot, root_action, choice, prefix, buckets, ranks,
                           average, actor, decision_index, behind, sidepot_count,
                           sidepot_amount, sidepot_eligible_mask, prune, reach, weighted,
                           per_sample)
                offset = 3 * pass_index
                for action in range(count):
                    for k in range(BATCH):
                        y = per_sample[action, k]
                        moments[task, action, offset] += y
                        moments[task, action, offset + 1] += y * y
                        moments[task, action, offset + 2] += y * prefix[k]
