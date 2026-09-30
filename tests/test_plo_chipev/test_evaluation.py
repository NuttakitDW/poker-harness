import random
import unittest

from plo_chipev.config import Config
from plo_chipev.evaluation import (
    FrozenAveragePolicy,
    action_label,
    domain_seed,
    evaluate_profile,
)
from plo_chipev.game import PreflopState
from plo_chipev.solver import Solver
from plo_icm.cards import deal
from plo_icm.game import Action


class EvaluationTest(unittest.TestCase):
    def test_holdout_report_counts_uniform_fallback_tiers_vpip_and_zero_sum(self):
        solver = Solver(Config(iterations=0, seed=3))

        report = evaluate_profile(solver, hands=4, seed=991)

        self.assertEqual(report["overall_vpip"]["clusters"], 4)
        self.assertEqual(
            sum(
                row["population"]
                for row in report["hwang_inspired_reporting_only"].values()
            ),
            24,
        )
        self.assertAlmostEqual(report["table_net_bb_per_100"], 0.0)
        self.assertLess(report["maximum_table_zero_sum_error_bb"], 1e-7)
        support_rows = [
            row
            for stages in report["average_policy_support"].values()
            for row in stages.values()
        ]
        self.assertTrue(support_rows)
        self.assertTrue(all(row["fallback_rate"] == 1.0 for row in support_rows))
        self.assertFalse(report["assumptions"]["ordinary_plo_optimum"])
        self.assertNotEqual(report["derived_seed"], 991)
        self.assertEqual(
            report["derived_seed"],
            domain_seed("behavior-evaluation", 991, report["profile_hash"]),
        )
        self.assertNotEqual(
            deal(random.Random(991)), deal(random.Random(report["derived_seed"]))
        )
        for tier in report["hwang_inspired_reporting_only"].values():
            for row in tier["actions_by_opportunity"].values():
                self.assertEqual(row["opportunities"], sum(row["counts"].values()))
                self.assertAlmostEqual(sum(row["rates"].values()), 1.0)

    def test_one_cluster_ci_is_not_reported_as_exact(self):
        report = evaluate_profile(Solver(Config(iterations=0)), hands=1, seed=1)
        self.assertFalse(report["overall_vpip"]["interval_available"])
        self.assertEqual(report["overall_vpip"]["lower_95"], 0.0)
        self.assertEqual(report["overall_vpip"]["upper_95"], 1.0)

    def test_limp_then_call_is_not_labeled_coldcall(self):
        state = PreflopState.new().apply(Action.CALL).apply(Action.POT)
        for _ in range(4):
            state = state.apply(Action.FOLD)
        self.assertEqual(state.actor, 0)
        self.assertEqual(action_label(state, Action.CALL), "limp_call")

    def test_frozen_policy_is_an_immutable_copy_of_average_strategy(self):
        solver = Solver(Config(iterations=1, seed=12, max_infosets=10_000))
        solver.train()
        policy = FrozenAveragePolicy(solver)
        frozen_hash = policy.profile_hash
        key = next(iter(solver.infosets))
        frozen_row = policy._profile[key]
        solver.infosets[key].strategy_sum[:] = 12345

        self.assertEqual(policy._profile[key], frozen_row)
        self.assertEqual(policy.profile_hash, frozen_hash)
