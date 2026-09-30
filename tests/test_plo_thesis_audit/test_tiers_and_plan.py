import inspect
import unittest

from plo_thesis_audit.cards import parse_hand
from plo_thesis_audit.plan import CANDIDATE_TEXTS, SCENARIOS, freeze_plan
from plo_thesis_audit.policy import ThesisBBPolicy
from plo_thesis_audit.tiers import TierLookup, classify_candidates


class TiersAndPlanTest(unittest.TestCase):
    def test_all_predeclared_candidate_classifications_are_validated(self):
        validation = classify_candidates(CANDIDATE_TEXTS)

        self.assertEqual(len(validation.valid) + len(validation.discarded), 12)
        self.assertTrue(all(row.tier == "Trash" for row in validation.valid))
        self.assertFalse(validation.discarded)


    def test_plan_freezes_all_cells_and_bonferroni_k_before_sampling(self):
        plan = freeze_plan(seed=29, phase="pilot")

        self.assertEqual(plan.accepted_per_cell, 2_000)
        self.assertEqual(plan.simultaneous_cells, len(plan.valid_candidates) * len(SCENARIOS))
        self.assertEqual(plan.simultaneous_cells, 36)
        self.assertEqual(len({cell.seed for cell in plan.cells}), 36)
        self.assertEqual(plan.status, "planned")
        main = freeze_plan(seed=29, phase="main")
        self.assertTrue({cell.seed for cell in plan.cells}.isdisjoint({cell.seed for cell in main.cells}))


    def test_hidden_bb_policy_cannot_receive_board_or_opponent_cards(self):
        signature = inspect.signature(ThesisBBPolicy.action)

        self.assertEqual(tuple(signature.parameters), ("self", "bb_tier"))
        policy = ThesisBBPolicy()
        self.assertEqual(policy.action("Trash"), "check")


    def test_full_lookup_uses_distinct_physical_hands_and_combinadic_slots(self):
        lookup = TierLookup.build(
            deck_size=8,
            classifier=lambda hand: "Trash" if 0 in hand else "Marginal",
            canonicalize_suits=False,
        )

        self.assertEqual(len(lookup), 70)
        self.assertEqual(lookup.tier((0, 1, 2, 3)), "Trash")
        self.assertEqual(lookup.tier((4, 5, 6, 7)), "Marginal")
        self.assertNotEqual(lookup.index((0, 2, 4, 7)), lookup.index((0, 2, 5, 7)))
        self.assertEqual(parse_hand("QsJs7c6c"), tuple(sorted(parse_hand("7c Qs 6c Js"))))
