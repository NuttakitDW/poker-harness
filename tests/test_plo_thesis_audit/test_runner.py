import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plo_thesis_audit.plan import freeze_plan
from plo_thesis_audit.runner import (
    _cell_row,
    atomic_write_json,
    report_is_complete,
    run_audit,
    source_hash,
)
from plo_thesis_audit.sampling import sample_cell


class AlwaysTrashLookup:
    classifier_calls = 1
    build_seconds = 0.01

    def tier(self, hand):
        return "Trash"

    def __len__(self):
        return 270_725


class RunnerTest(unittest.TestCase):
    def test_draw_guard_produces_partial_result_that_cannot_claim_complete(self):
        cell = freeze_plan(seed=5, phase="pilot").cells[0]

        result = sample_cell(
            cell,
            accepted_target=10,
            lookup=AlwaysTrashLookup(),
            max_draws=3,
        )

        self.assertEqual(result.accepted, 3)
        self.assertFalse(result.complete)
        self.assertEqual(result.stop_reason, "max_draws")
        self.assertFalse(report_is_complete([result], expected_cells=1, accepted_per_cell=10))
        self.assertIsNone(_cell_row(result, cells=36)["simultaneous_hoeffding"])


    def test_seed_replay_is_deterministic(self):
        cell = freeze_plan(seed=991, phase="pilot").cells[0]

        first = sample_cell(cell, accepted_target=20, lookup=AlwaysTrashLookup())
        second = sample_cell(cell, accepted_target=20, lookup=AlwaysTrashLookup())

        self.assertEqual(first, second)


    def test_atomic_json_and_source_hash_are_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested" / "result.json"
            payload = {"status": "partial", "source_hash": source_hash()}

            atomic_write_json(destination, payload)

            self.assertEqual(json.loads(destination.read_text()), payload)
            self.assertEqual(source_hash(), payload["source_hash"])
            self.assertFalse(list(destination.parent.glob("*.tmp")))

    def test_small_pilot_orchestration_writes_complete_self_describing_report(self):
        original = freeze_plan(seed=18, phase="pilot")
        plan = dataclasses.replace(
            original,
            accepted_per_cell=3,
            cells=original.cells[:1],
            simultaneous_cells=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "pilot.json"
            with patch(
                "plo_thesis_audit.runner.TierLookup.build",
                return_value=AlwaysTrashLookup(),
            ):
                report = run_audit(plan, output=destination)

            saved = json.loads(destination.read_text())
            self.assertEqual(report["status"], "complete")
            self.assertEqual(saved["accepted_total"], 3)
            self.assertEqual(saved["cells"][0]["hero_tier"], "Trash")
            self.assertEqual(
                saved["cells"][0]["prior_fold_condition"]["BTN"], "Trash only"
            )
            self.assertIn("recommended_main_budget_seconds", saved)
            self.assertEqual(saved["assumptions"]["format"], "tournament chip EV")
            self.assertIn("call or fold", saved["assumptions"]["preflop"])
            bound = saved["cells"][0]["simultaneous_hoeffding"]
            self.assertIn("upper_conservative_surrogate_bb", bound)
            self.assertNotIn("upper_true_deviation_gain_bb", bound)
            self.assertIn("transitive_hash", saved["provenance"])
            self.assertTrue(
                any("phevaluator-native" in key for key in saved["provenance"]["dependency_hashes"])
            )

    def test_partial_orchestration_suppresses_every_inferential_bound(self):
        original = freeze_plan(seed=19, phase="pilot")
        plan = dataclasses.replace(
            original,
            accepted_per_cell=3,
            cells=original.cells[:1],
            simultaneous_cells=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "partial.json"
            with patch(
                "plo_thesis_audit.runner.TierLookup.build",
                return_value=AlwaysTrashLookup(),
            ):
                report = run_audit(plan, output=destination, max_draws_per_cell=1)

        self.assertEqual(report["status"], "partial")
        self.assertIsNone(report["cells"][0]["simultaneous_hoeffding"])
