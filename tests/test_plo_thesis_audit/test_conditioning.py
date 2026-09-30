import itertools
import random
import unittest

from plo_thesis_audit.cards import full_deal
from plo_thesis_audit.plan import SCENARIOS
from plo_thesis_audit.sampling import earlier_four_fold


class RecordingLookup:
    def __init__(self, tiers):
        self.tiers = iter(tiers)
        self.hands = []

    def tier(self, hand):
        self.hands.append(tuple(hand))
        return next(self.tiers)


class ConditioningTest(unittest.TestCase):
    def test_fixed_hero_is_removed_and_fold_condition_uses_all_four_prior_hands(self):
        hero = (0, 1, 2, 3)
        dealt = full_deal(random.Random(11), hero)
        lookup = RecordingLookup(("Trash", "Marginal", "Trash", "Trash"))

        accepted = earlier_four_fold(dealt.earlier_holes, SCENARIOS[0], lookup)

        self.assertTrue(accepted)
        self.assertEqual(lookup.hands, list(dealt.earlier_holes))
        used = set(hero)
        for group in (*dealt.earlier_holes, dealt.bb_hole, dealt.board):
            self.assertTrue(used.isdisjoint(group))
            used.update(group)
        self.assertEqual(len(used), 29)


    def test_late_marginal_entry_scenarios_change_the_fold_event_by_position(self):
        holes = tuple(tuple(group) for group in itertools.batched(range(16), 4))

    # HJ Marginal folds in the first two authored scenarios but enters in the third.
        tiers = ("Trash", "Marginal", "Trash", "Trash")
        outcomes = []
        for scenario in SCENARIOS:
            outcomes.append(earlier_four_fold(holes, scenario, RecordingLookup(tiers)))

        self.assertEqual(outcomes, [True, True, False])
