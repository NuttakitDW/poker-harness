import itertools
import unittest

from plo_chipev.certificate import (
    RANGE_BB,
    TARGET_BB,
    SampleNode,
    baseline_value,
    empirical_bernstein_upper,
    grouped_best_response,
    statistical_floor,
    target_information_key,
)
from plo_chipev.config import Config
from plo_chipev.solver import Solver


def target(key, rewards, probabilities=(0.5, 0.5)):
    return SampleNode.target(
        key,
        tuple(SampleNode.leaf(reward) for reward in rewards),
        probabilities,
        depth=0,
    )


class CertificateDPTest(unittest.TestCase):
    def test_grouped_policy_matches_exhaustive_and_blocks_clairvoyant_world_choice(self):
        roots = [target("same-own-info", (1, 0)), target("same-own-info", (0, 1))]

        optimized, choices = grouped_best_response(roots)
        exhaustive = max(
            sum(root.children[action].payoff for root in roots) / len(roots)
            for action in range(2)
        )
        clairvoyant = sum(max(child.payoff for child in root.children) for root in roots) / 2

        self.assertEqual(optimized, exhaustive)
        self.assertEqual(optimized, 0.5)
        self.assertEqual(clairvoyant, 1.0)
        self.assertEqual(sum(baseline_value(root) for root in roots) / 2, 0.5)
        self.assertIn(choices["same-own-info"], (0, 1))

    def test_different_own_information_can_choose_different_actions(self):
        roots = [target("hand-a", (1, 0)), target("hand-b", (0, 1))]
        optimized, choices = grouped_best_response(roots)
        self.assertEqual(optimized, 1.0)
        self.assertEqual(choices, {"hand-a": 0, "hand-b": 1})

    def test_exploitative_and_equilibrium_toys(self):
        exploitative = [target("same", (1, 0)), target("same", (1, 0))]
        optimized, _ = grouped_best_response(exploitative)
        baseline = sum(map(baseline_value, exploitative)) / 2
        self.assertEqual((optimized, baseline, optimized - baseline), (1.0, 0.5, 0.5))

        equilibrium = [target("same", (1, 0), (1.0, 0.0)) for _ in range(2)]
        optimized, _ = grouped_best_response(equilibrium)
        baseline = sum(map(baseline_value, equilibrium)) / 2
        self.assertEqual(optimized - baseline, 0.0)

    def test_empirical_bernstein_units_round_spending_and_incomplete_case(self):
        samples = list(itertools.repeat(0.0, 10_000))
        first = empirical_bernstein_upper(samples, alpha=0.05, round_index=1)
        second = empirical_bernstein_upper(samples, alpha=0.05, round_index=2)
        self.assertGreaterEqual(second, first)
        self.assertGreater(first, TARGET_BB)
        self.assertEqual(empirical_bernstein_upper([], alpha=0.05, round_index=1), RANGE_BB)

    def test_certificate_exact_key_excludes_hidden_state_and_keeps_physical_suits(self):
        history = ("0:0:call:1",)
        first = target_information_key(("As", "Ks", "Qd", "Jd"), history)
        reordered = target_information_key(("Jd", "Qd", "Ks", "As"), history)
        renamed = target_information_key(("Ah", "Kh", "Qc", "Jc"), history)
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, renamed)
        self.assertEqual(first, target_information_key(first[0], history))

    def test_certification_uses_separate_rng_and_does_not_mutate_frozen_policy(self):
        from plo_chipev.certificate import certify_profile

        solver = Solver(Config(iterations=1, seed=22, max_infosets=10_000))
        solver.train()
        before = solver.snapshot()
        report = certify_profile(
            solver,
            batches=2,
            batch_hands=1,
            seed=91,
            alpha=0.05,
            round_index=1,
        )
        self.assertEqual(solver.snapshot(), before)
        self.assertTrue(report["complete"])
        self.assertFalse(report["certified"])

    def test_round_and_nonce_domain_separate_certificate_samples(self):
        from plo_chipev.certificate import _seed

        first = _seed(7, 0, 0, round_index=1, nonce="a", profile_hash="p")
        self.assertNotEqual(
            first, _seed(7, 0, 0, round_index=2, nonce="a", profile_hash="p")
        )
        self.assertNotEqual(
            first, _seed(7, 0, 0, round_index=1, nonce="b", profile_hash="p")
        )

    def test_node_guard_discards_partial_batch_and_cannot_certify(self):
        from plo_chipev.certificate import certify_profile

        solver = Solver(Config(iterations=0))
        report = certify_profile(
            solver,
            batches=2,
            batch_hands=1,
            seed=2,
            alpha=0.05,
            round_index=1,
            max_nodes=1,
            nonce="fixed-test-nonce",
        )
        self.assertFalse(report["complete"])
        self.assertFalse(report["certified"])
        self.assertEqual(report["nodes"], 1)
        self.assertEqual(report["by_target_seat"]["0"]["completed_batches"], 0)

    def test_time_guard_discards_partial_batch_and_cannot_certify(self):
        from plo_chipev.certificate import certify_profile

        report = certify_profile(
            Solver(Config(iterations=0)),
            batches=2,
            batch_hands=1,
            seed=3,
            alpha=0.05,
            round_index=1,
            max_seconds=1e-12,
            nonce="fixed-time-guard",
        )
        self.assertFalse(report["complete"])
        self.assertFalse(report["certified"])
        self.assertEqual(report["by_target_seat"]["0"]["completed_batches"], 0)

    def test_tiny_planned_budget_reports_unreachable_best_case_floor(self):
        self.assertEqual(
            statistical_floor(batches=2, alpha=0.05, round_index=1), RANGE_BB
        )
        report = __import__(
            "plo_chipev.certificate", fromlist=["certify_profile"]
        ).certify_profile(
            Solver(Config(iterations=0)),
            batches=2,
            batch_hands=1,
            seed=3,
            alpha=0.05,
            round_index=1,
            max_nodes=1,
            nonce="floor-diagnostic",
        )
        self.assertEqual(report["best_case_statistical_floor_bb"], RANGE_BB)
        self.assertFalse(report["planned_budget_can_reach_target"])

    def test_certificate_rejects_nonfinite_and_boolean_public_budgets(self):
        from plo_chipev.certificate import certify_profile

        solver = Solver(Config(iterations=0))
        bad_calls = (
            {"batches": True},
            {"batch_hands": True},
            {"alpha": float("nan")},
            {"alpha": float("inf")},
            {"round_index": True},
            {"max_nodes": True},
            {"max_seconds": True},
            {"max_seconds": float("nan")},
            {"max_seconds": float("inf")},
        )
        defaults = {
            "batches": 2,
            "batch_hands": 1,
            "seed": 1,
            "alpha": 0.05,
            "round_index": 1,
            "max_nodes": 1,
            "max_seconds": 0.1,
            "nonce": "validation",
        }
        for replacement in bad_calls:
            with self.subTest(replacement=replacement), self.assertRaises(
                (TypeError, ValueError)
            ):
                certify_profile(solver, **(defaults | replacement))
