from __future__ import annotations

import random
import unittest

import numpy as np

from plo_chipev.game import PreflopState
from plo_chipev.showdown import settle_by_ranks
from plo_chipev_fast.trainer import _terminal_target_utility
from plo_chipev_fast.tree import ACTION_NAMES, PublicTree, settle_terminal
from plo_icm.game import Action


class PublicTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = PublicTree.build()

    def test_full_tree_has_expected_shape_and_exact_transitions(self) -> None:
        self.assertEqual(self.tree.node_count, 11_566)
        self.assertEqual(self.tree.decision_count, 5_466)
        self.assertEqual(self.tree.terminal_count, 6_100)
        self.assertEqual(len(set(self.tree.histories)), self.tree.node_count)
        for node, history in enumerate(self.tree.histories):
            state = PreflopState.new()
            for event in history:
                state = state.apply(Action(event.split(":")[2]))
            self.assertEqual(self.tree.actor[node], -1 if state.terminal else state.actor)
            legal = tuple(action.value for action in state.legal_actions())
            self.assertEqual(
                tuple(ACTION_NAMES[value] for value in self.tree.action_ids[node, : len(legal)]),
                legal,
            )
            for offset, action in enumerate(state.legal_actions()):
                child = int(self.tree.children[node, offset])
                self.assertEqual(self.tree.histories[child], state.apply(action).history)

    def test_terminal_settlement_matches_original_for_every_terminal(self) -> None:
        rng = random.Random(9123)
        for node in np.flatnonzero(self.tree.actor < 0):
            ranks = (
                (100, 100, 200, 300, 400, 500)
                if node % 3 == 0
                else tuple(rng.randrange(1, 7_500) for _ in range(6))
            )
            expected = settle_by_ranks(
                self.tree.behind[node],
                self.tree.committed[node],
                frozenset(
                    seat for seat in range(6) if self.tree.folded_mask[node] & (1 << seat)
                ),
                ranks,
                self.tree.dead_money[node],
            )
            actual = settle_terminal(self.tree, int(node), np.asarray(ranks, dtype=np.int32))
            np.testing.assert_allclose(actual, expected, atol=1e-10)
            native = np.asarray(
                [
                    _terminal_target_utility(
                        int(node),
                        seat,
                        self.tree.behind,
                        self.tree.sidepot_count,
                        self.tree.sidepot_amount,
                        self.tree.sidepot_eligible_mask,
                        np.asarray(ranks, dtype=np.int32),
                    )
                    + 100.0
                    for seat in range(6)
                ]
            )
            np.testing.assert_allclose(native, expected, atol=1e-10)
            self.assertAlmostEqual(float(actual.sum()), 600.0, places=8)
            self.assertAlmostEqual(
                float(self.tree.sidepot_amount[node].sum()),
                float(self.tree.committed[node].sum() + self.tree.dead_money[node]),
                places=8,
            )

    def test_native_terminal_payoff_matches_synthetic_all_in_sidepots_folds_and_ties(self) -> None:
        cases = (
            (
                np.array([[0, 0, 40, 60, 80, 90]], dtype=np.float64),
                np.array([[100, 100, 60, 40, 20, 10]], dtype=np.float64),
                frozenset((1, 4)),
                np.array((10, 1, 10, 30, 5, 40), dtype=np.int32),
                0.0,
            ),
            (
                np.array([[0, 50, 75, 90, 95, 99]], dtype=np.float64),
                np.array([[100, 50, 25, 10, 5, 1]], dtype=np.float64),
                frozenset((2, 3, 4, 5)),
                np.array((100, 20, 1, 1, 1, 1), dtype=np.int32),
                3.0,
            ),
        )
        for behind, committed, folded, ranks, dead_money in cases:
            levels = sorted({float(value) for value in committed[0] if value > 1e-9})
            count = np.array((len(levels),), dtype=np.int8)
            amounts = np.zeros((1, 6), dtype=np.float64)
            eligible_masks = np.zeros((1, 6), dtype=np.uint8)
            previous = 0.0
            for layer, level in enumerate(levels):
                contributors = tuple(
                    seat for seat, value in enumerate(committed[0]) if value + 1e-9 >= level
                )
                eligible = tuple(seat for seat in contributors if seat not in folded)
                amounts[0, layer] = (level - previous) * len(contributors)
                if layer == 0:
                    amounts[0, layer] += dead_money
                eligible_masks[0, layer] = sum(1 << seat for seat in eligible)
                previous = level
            expected = settle_by_ranks(
                behind[0], committed[0], folded, ranks, dead_money
            )
            actual = np.array(
                [
                    _terminal_target_utility(
                        0, seat, behind, count, amounts, eligible_masks, ranks
                    )
                    + 100.0
                    for seat in range(6)
                ]
            )
            np.testing.assert_allclose(actual, expected, atol=1e-10)
