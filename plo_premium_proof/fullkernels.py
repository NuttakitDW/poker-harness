"""External-sampling MCCFR and profile evaluation for the all-streets game.

Buckets are resolved lazily per deal: a street's board distribution and each
seat's bucket are only computed when a traversal first reaches that street.
Regret and strategy tables are flat ``(rows, 3)`` arrays addressed by
``row_start[decision] + bucket``.
"""

from __future__ import annotations

import numpy as np
from numba import njit, prange

from plo_chipev_fast.trainer import _random_unit

from .kernels import _deal, _situation, tree_links  # noqa: F401
from .postflop import board_distribution, postflop_bucket

DISTRIBUTION_SIZE = 1176


@njit(cache=True)  # pragma: no cover - compiled native code
def _utility(node: int, target: int, stack: float, behind: np.ndarray, sidepot_count: np.ndarray,
             sidepot_amount: np.ndarray, sidepot_eligible_mask: np.ndarray, ranks: np.ndarray) -> float:
    """Chips ``target`` ends with minus the starting stack (ties split exactly)."""
    result = behind[node, target]
    for layer in range(sidepot_count[node]):
        best = 1 << 30
        winners = 0
        target_wins = False
        mask = sidepot_eligible_mask[node, layer]
        for seat in range(6):
            if mask & (1 << seat):
                if ranks[seat] < best:
                    best = ranks[seat]
                    winners = 1
                    target_wins = seat == target
                elif ranks[seat] == best:
                    winners += 1
                    target_wins = target_wins or seat == target
        if target_wins:
            result += sidepot_amount[node, layer] / winners
    return result - stack

# Numba cannot reload cached recursive functions, so recursive kernels are not cached.


@njit(cache=True)  # pragma: no cover - compiled native code
def _bucket(street: int, seat: int, hands: np.ndarray, board: np.ndarray, buckets: np.ndarray,
            distributions: np.ndarray, counts: np.ndarray, rank5: np.ndarray, comb: np.ndarray) -> int:
    """``buckets[street, seat]``; -1 marks not yet computed for this deal."""
    cached = buckets[street, seat]
    if cached >= 0:
        return cached
    if counts[street] == 0:
        counts[street] = board_distribution(board, street + 2, rank5, comb, distributions[street])
    value = postflop_bucket(hands[seat], board, street, distributions[street], counts[street], rank5, comb)
    buckets[street, seat] = value
    return value


@njit(cache=True)  # pragma: no cover - compiled native code
def _reset_deal(buckets: np.ndarray, counts: np.ndarray, preflop: np.ndarray) -> None:
    for seat in range(6):
        buckets[0, seat] = preflop[seat]
        for street in range(1, 4):
            buckets[street, seat] = -1
    for street in range(4):
        counts[street] = 0


@njit(cache=True)  # pragma: no cover - compiled native code
def _strategy(regrets: np.ndarray, row: int, count: int) -> tuple[float, float, float]:
    p0 = max(regrets[row, 0], 0.0)
    p1 = max(regrets[row, 1], 0.0) if count > 1 else 0.0
    p2 = max(regrets[row, 2], 0.0) if count > 2 else 0.0
    total = p0 + p1 + p2
    if total <= 0.0:
        uniform = 1.0 / count
        return uniform, uniform if count > 1 else 0.0, uniform if count > 2 else 0.0
    return p0 / total, p1 / total, p2 / total


@njit()  # pragma: no cover - compiled native code
def _traverse(
    node: int, traverser: int, hands: np.ndarray, board: np.ndarray, buckets: np.ndarray,
    distributions: np.ndarray, counts: np.ndarray, ranks: np.ndarray, rank5: np.ndarray,
    comb: np.ndarray, actor: np.ndarray, street: np.ndarray, decision_index: np.ndarray,
    row_start: np.ndarray, children: np.ndarray, action_count: np.ndarray, behind: np.ndarray,
    sidepot_count: np.ndarray, sidepot_amount: np.ndarray, sidepot_eligible_mask: np.ndarray,
    regrets: np.ndarray, strategy_sum: np.ndarray, state: np.ndarray, stack: float,
) -> float:
    seat = actor[node]
    if seat < 0:
        return _utility(node, traverser, stack, behind, sidepot_count, sidepot_amount,
                        sidepot_eligible_mask, ranks)
    bucket = _bucket(street[node], seat, hands, board, buckets, distributions, counts, rank5, comb)
    row = row_start[decision_index[node]] + bucket
    count = action_count[node]
    p0, p1, p2 = _strategy(regrets, row, count)
    if seat == traverser:
        v0 = _traverse(
            children[node, 0], traverser, hands, board, buckets, distributions, counts, ranks,
            rank5, comb, actor, street, decision_index, row_start, children, action_count,
            behind, sidepot_count, sidepot_amount, sidepot_eligible_mask, regrets,
            strategy_sum, state, stack,
        )
        v1 = 0.0
        v2 = 0.0
        if count > 1:
            v1 = _traverse(
                children[node, 1], traverser, hands, board, buckets, distributions, counts,
                ranks, rank5, comb, actor, street, decision_index, row_start, children,
                action_count, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
                regrets, strategy_sum, state, stack,
            )
        if count > 2:
            v2 = _traverse(
                children[node, 2], traverser, hands, board, buckets, distributions, counts,
                ranks, rank5, comb, actor, street, decision_index, row_start, children,
                action_count, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
                regrets, strategy_sum, state, stack,
            )
        expected = p0 * v0 + p1 * v1 + p2 * v2
        regrets[row, 0] += v0 - expected
        if count > 1:
            regrets[row, 1] += v1 - expected
        if count > 2:
            regrets[row, 2] += v2 - expected
        return expected
    strategy_sum[row, 0] += p0
    if count > 1:
        strategy_sum[row, 1] += p1
    if count > 2:
        strategy_sum[row, 2] += p2
    point = _random_unit(state)
    choice = 0
    if point > p0:
        choice = 1 if (count == 2 or point <= p0 + p1) else 2
    return _traverse(
        children[node, choice], traverser, hands, board, buckets, distributions, counts, ranks,
        rank5, comb, actor, street, decision_index, row_start, children, action_count, behind,
        sidepot_count, sidepot_amount, sidepot_eligible_mask, regrets, strategy_sum, state, stack,
    )


@njit(parallel=True)  # pragma: no cover - compiled native code
def train_full(
    deals_per_thread: int, rng_states: np.ndarray, bucket_of: np.ndarray, rank5: np.ndarray,
    comb: np.ndarray, actor: np.ndarray, street: np.ndarray, decision_index: np.ndarray,
    row_start: np.ndarray, children: np.ndarray, action_count: np.ndarray, behind: np.ndarray,
    sidepot_count: np.ndarray, sidepot_amount: np.ndarray, sidepot_eligible_mask: np.ndarray,
    regrets: np.ndarray, strategy_sum: np.ndarray, stack: float,
) -> None:
    """Hogwild MCCFR: one deal per step, traversed once for each of the six seats."""
    for thread in prange(rng_states.size):
        state = rng_states[thread:thread + 1]
        hands = np.empty((6, 4), dtype=np.int64)
        board = np.empty(5, dtype=np.int64)
        preflop = np.empty(6, dtype=np.int64)
        ranks = np.empty(6, dtype=np.int64)
        buckets = np.empty((4, 6), dtype=np.int64)
        distributions = np.empty((4, DISTRIBUTION_SIZE), dtype=np.int64)
        counts = np.zeros(4, dtype=np.int64)
        none = np.empty(4, dtype=np.int64)
        for _ in range(deals_per_thread):
            _deal(state, -1, none, hands, board)
            _situation(hands, board, bucket_of, rank5, comb, preflop, ranks)
            _reset_deal(buckets, counts, preflop)
            for traverser in range(6):
                _traverse(
                    0, traverser, hands, board, buckets, distributions, counts, ranks, rank5,
                    comb, actor, street, decision_index, row_start, children, action_count,
                    behind, sidepot_count, sidepot_amount, sidepot_eligible_mask,
                    regrets, strategy_sum, state, stack,
                )


BATCH = 32


@njit(parallel=True)  # pragma: no cover - compiled native code
def evaluate_root_actions(
    task_cards: np.ndarray, task_seat: np.ndarray, task_seed: np.ndarray, batches: int,
    first_in_nodes: np.ndarray, bucket_of: np.ndarray, rank5: np.ndarray, comb: np.ndarray,
    policy: np.ndarray, actor: np.ndarray, street: np.ndarray, decision_index: np.ndarray,
    row_start: np.ndarray, action_count: np.ndarray, behind: np.ndarray,
    sidepot_count: np.ndarray, sidepot_amount: np.ndarray, sidepot_eligible_mask: np.ndarray,
    parent: np.ndarray, parent_slot: np.ndarray, subtree_end: np.ndarray, prune: float,
    stack: float, moments: np.ndarray,
) -> None:
    """One-step deviation values at hero's first-in node.

    Hero takes each root action, then everyone (hero included) follows the solved
    average profile. Earlier seats' folds weight each deal by their probability.
    ``moments[t, a, :3]`` = sums of y, y^2, y*z per root action; ``moments[t, 3, :2]``
    = sums of z, z^2 (z = chance all earlier seats folded).
    """
    nodes = actor.size
    for task in prange(task_cards.shape[0]):
        hero = task_seat[task]
        root = first_in_nodes[hero]
        end = subtree_end[root]
        state = task_seed[task:task + 1].copy()
        hero_cards = task_cards[task]
        hands = np.empty((BATCH, 6, 4), dtype=np.int64)
        board = np.empty((BATCH, 5), dtype=np.int64)
        ranks = np.empty((BATCH, 6), dtype=np.int64)
        buckets = np.empty((BATCH, 4, 6), dtype=np.int64)
        distributions = np.empty((BATCH, 4, DISTRIBUTION_SIZE), dtype=np.int64)
        counts = np.zeros((BATCH, 4), dtype=np.int64)
        preflop = np.empty(6, dtype=np.int64)
        prefix = np.empty(BATCH, dtype=np.float64)
        reach = np.zeros((nodes, BATCH), dtype=np.float64)
        per_sample = np.zeros((3, BATCH), dtype=np.float64)
        root_action = np.zeros(nodes, dtype=np.int64)
        for node in range(root + 1, end + 1):
            up = parent[node]
            root_action[node] = parent_slot[node] if up == root else root_action[up]
        count_root = action_count[root]
        for _ in range(batches):
            for k in range(BATCH):
                _deal(state, hero, hero_cards, hands[k], board[k])
                _situation(hands[k], board[k], bucket_of, rank5, comb, preflop, ranks[k])
                _reset_deal(buckets[k], counts[k], preflop)
                z = 1.0
                for seat in range(hero):
                    row = row_start[decision_index[first_in_nodes[seat]]] + preflop[seat]
                    z *= policy[row, 0]
                prefix[k] = z
                reach[root, k] = z
                moments[task, 3, 0] += z
                moments[task, 3, 1] += z * z
            per_sample[:, :] = 0.0
            node = root + 1
            while node <= end:
                up = parent[node]
                slot = parent_slot[node]
                seat = actor[up]
                live = False
                for k in range(BATCH):
                    above = reach[up, k]
                    value = 0.0
                    if above > prune:
                        if up == root:
                            value = above
                        else:
                            bucket = _bucket(street[up], seat, hands[k], board[k], buckets[k],
                                             distributions[k], counts[k], rank5, comb)
                            value = above * policy[row_start[decision_index[up]] + bucket, slot]
                    reach[node, k] = value
                    if value > prune:
                        live = True
                if not live:
                    node = subtree_end[node] + 1
                    continue
                if actor[node] < 0:
                    for k in range(BATCH):
                        value = reach[node, k]
                        if value > prune:
                            per_sample[root_action[node], k] += value * _utility(
                                node, hero, stack, behind, sidepot_count, sidepot_amount,
                                sidepot_eligible_mask, ranks[k])
                node += 1
            for action in range(count_root):
                for k in range(BATCH):
                    y = per_sample[action, k]
                    moments[task, action, 0] += y
                    moments[task, action, 1] += y * y
                    moments[task, action, 2] += y * prefix[k]


@njit(cache=True)  # pragma: no cover - compiled native code
def _average_action(strategy_sum: np.ndarray, row: int, count: int, state: np.ndarray) -> int:
    """Sample from the normalized average strategy (uniform over legal if never visited)."""
    s0 = strategy_sum[row, 0]
    s1 = strategy_sum[row, 1] if count > 1 else 0.0
    s2 = strategy_sum[row, 2] if count > 2 else 0.0
    total = s0 + s1 + s2
    point = _random_unit(state)
    if total <= 0.0:
        return min(int(point * count), count - 1)
    point *= total
    if point < s0:
        return 0
    if count == 2 or point < s0 + s1:
        return 1
    return 2


@njit(cache=True)  # pragma: no cover - compiled native code
def _fold_probability(strategy_sum: np.ndarray, row: int, count: int) -> float:
    total = strategy_sum[row, 0] + strategy_sum[row, 1] + (strategy_sum[row, 2] if count > 2 else 0.0)
    return strategy_sum[row, 0] / total if total > 0.0 else 1.0 / count


@njit(parallel=True)  # pragma: no cover - compiled native code
def sample_root_actions(
    task_cards: np.ndarray, task_seat: np.ndarray, task_seed: np.ndarray, samples: int,
    first_in_nodes: np.ndarray, bucket_of: np.ndarray, rank5: np.ndarray, comb: np.ndarray,
    strategy_sum: np.ndarray, actor: np.ndarray, street: np.ndarray, decision_index: np.ndarray,
    row_start: np.ndarray, children: np.ndarray, action_count: np.ndarray, behind: np.ndarray,
    sidepot_count: np.ndarray, sidepot_amount: np.ndarray, sidepot_eligible_mask: np.ndarray,
    stack: float, moments: np.ndarray,
) -> None:
    """Sampled one-step deviation values at hero's first-in node (for trees too big to walk).

    Each deal plays one path per root action with every player, hero included, drawing
    actions from the average strategy; the root actions share the deal. Same moment layout
    as ``evaluate_root_actions``.
    """
    for task in prange(task_cards.shape[0]):
        hero = task_seat[task]
        root = first_in_nodes[hero]
        state = task_seed[task:task + 1].copy()
        hero_cards = task_cards[task]
        hands = np.empty((6, 4), dtype=np.int64)
        board = np.empty(5, dtype=np.int64)
        preflop = np.empty(6, dtype=np.int64)
        ranks = np.empty(6, dtype=np.int64)
        buckets = np.empty((4, 6), dtype=np.int64)
        distributions = np.empty((4, DISTRIBUTION_SIZE), dtype=np.int64)
        counts = np.zeros(4, dtype=np.int64)
        count_root = action_count[root]
        for _ in range(samples):
            _deal(state, hero, hero_cards, hands, board)
            _situation(hands, board, bucket_of, rank5, comb, preflop, ranks)
            _reset_deal(buckets, counts, preflop)
            z = 1.0
            for seat in range(hero):
                node = first_in_nodes[seat]
                z *= _fold_probability(strategy_sum, row_start[decision_index[node]] + preflop[seat],
                                       action_count[node])
            moments[task, 3, 0] += z
            moments[task, 3, 1] += z * z
            if z <= 0.0:
                continue
            for action in range(count_root):
                node = children[root, action]
                while actor[node] >= 0:
                    seat = actor[node]
                    bucket = _bucket(street[node], seat, hands, board, buckets, distributions, counts, rank5, comb)
                    choice = _average_action(strategy_sum, row_start[decision_index[node]] + bucket,
                                             action_count[node], state)
                    node = children[node, choice]
                y = z * _utility(node, hero, stack, behind, sidepot_count, sidepot_amount,
                                 sidepot_eligible_mask, ranks)
                moments[task, action, 0] += y
                moments[task, action, 1] += y * y
                moments[task, action, 2] += y * z
