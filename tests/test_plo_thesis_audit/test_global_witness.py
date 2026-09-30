import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plo_thesis_audit.evaluator import showdown_share
from plo_thesis_audit.global_witness import (
    GLOBAL_CUTOFFS,
    GlobalWitnessResult,
    freeze_global_plan,
    global_symmetry_value,
    run_global_audit,
    sample_global_witness,
)


class AlwaysTrashLookup:
    classifier_calls = 1
    build_seconds = 0.01

    def tier(self, hand):
        return "Trash"

    def __len__(self):
        return 270_725


class GlobalWitnessTest(unittest.TestCase):
    def test_five_cutoffs_are_frozen_from_utg_through_sb(self):
        self.assertEqual(
            tuple(cutoff.position for cutoff in GLOBAL_CUTOFFS),
            ("UTG", "HJ", "CO", "BTN", "SB"),
        )
        self.assertEqual(
            GLOBAL_CUTOFFS[0].fold_condition(),
            {"UTG": "Trash only", "HJ": "Trash only", "CO": "Trash only", "BTN": "Trash only"},
        )
        self.assertEqual(
            GLOBAL_CUTOFFS[-1].fold_condition(),
            {
                "UTG": "Trash or Marginal",
                "HJ": "Trash or Marginal",
                "CO": "Trash or Marginal",
                "BTN": "Trash or Marginal",
            },
        )

    def test_global_symmetry_value_has_range_one_and_zero_for_unreached_deals(self):
        self.assertEqual(global_symmetry_value(d_event=False, bb_trash=False), 0.0)
        self.assertEqual(global_symmetry_value(d_event=False, bb_trash=True), 0.0)
        self.assertEqual(global_symmetry_value(d_event=True, bb_trash=False), -0.5)
        self.assertEqual(global_symmetry_value(d_event=True, bb_trash=True), 0.5)

    def test_exact_swap_symmetry_payoff_identity_including_ties(self):
        # Exact toy board enumeration. Swapping SB/BB maps every share s to 1-s;
        # the middle board is a tie and maps to itself.
        forward_shares = (1.0, 0.5, 0.0)
        swapped_shares = (0.0, 0.5, 1.0)
        all_shares = forward_shares + swapped_shares
        actual_lower_payoffs = tuple(2 * share - 0.5 for share in all_shares)

        self.assertEqual(sum(all_shares) / len(all_shares), 0.5)
        self.assertEqual(sum(actual_lower_payoffs) / len(actual_lower_payoffs), 0.5)
        self.assertEqual(global_symmetry_value(d_event=True, bb_trash=True), 0.5)

    def test_direct_board_diagnostic_has_exact_swap_average(self):
        hero = (48, 44, 21, 17)  # Ac Kc 7d 6d
        bb = (47, 43, 14, 10)  # Ks Qs 5h 4h
        boards = (
            (0, 5, 11, 15, 20),
            (1, 6, 12, 16, 22),
            (2, 7, 13, 18, 23),
        )
        for board in boards:
            with self.subTest(board=board):
                forward = showdown_share(hero, bb, board)
                swapped = showdown_share(bb, hero, board)
                self.assertEqual((forward + swapped) / 2, 0.5)

    def test_main_plan_freezes_one_million_iid_deals_before_sampling(self):
        pilot = freeze_global_plan(seed=77, phase="pilot")
        main = freeze_global_plan(seed=77, phase="main")

        self.assertEqual(main.deals, 1_000_000)
        self.assertEqual(main.simultaneous_cells, 5)
        self.assertEqual(len(main.cutoffs), 5)
        self.assertEqual(main.status, "planned")
        self.assertNotEqual(pilot.seed, main.seed)

    def test_seeded_global_sampling_replays_and_evaluates_every_cutoff(self):
        plan = freeze_global_plan(seed=991, phase="pilot", pilot_deals=30)
        with patch(
            "plo_thesis_audit.evaluator.showdown_share",
            side_effect=AssertionError("global estimator must not evaluate boards"),
        ):
            first = sample_global_witness(plan, lookup=AlwaysTrashLookup())
            second = sample_global_witness(plan, lookup=AlwaysTrashLookup())

        self.assertEqual(first, second)
        self.assertEqual(first.deals_completed, 30)
        self.assertEqual(len(first.cells), 5)
        self.assertTrue(first.complete)
        self.assertTrue(all(cell.d_event_count == 30 for cell in first.cells))
        self.assertTrue(all(cell.mean_y_bb_per_initial_deal == 0.5 for cell in first.cells))

    def test_global_guard_is_partial_and_report_has_no_bounds(self):
        plan = freeze_global_plan(seed=22, phase="pilot", pilot_deals=10)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "global.json"
            with patch(
                "plo_thesis_audit.global_witness.TierLookup.build",
                return_value=AlwaysTrashLookup(),
            ):
                report = run_global_audit(
                    plan,
                    output=destination,
                    max_deals=3,
                )
            saved = json.loads(destination.read_text())

        self.assertEqual(report["status"], "partial")
        self.assertEqual(saved["deals_completed"], 3)
        self.assertFalse(saved["confirmatory_witness_established"])
        self.assertFalse(saved["confirmatory_threshold_0_015_rejected"])
        self.assertTrue(all(cell["inference"] is None for cell in saved["cells"]))

    def test_positive_empirical_mean_is_labeled_diagnostic_only(self):
        result = GlobalWitnessResult.synthetic_for_test(mean_surrogate_bb=0.01)

        self.assertTrue(result.has_positive_empirical_mean_diagnostic())
