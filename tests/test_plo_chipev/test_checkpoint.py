import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from plo_chipev.checkpoint import (
    _digest,
    initialize_round_ledger,
    load_checkpoint,
    load_round_high_water,
    reserve_evaluation_round,
    round_ledger_path,
    save_checkpoint,
)
from plo_chipev.config import Config
from plo_chipev.solver import Solver


class CheckpointTest(unittest.TestCase):
    def test_split_save_resume_matches_uninterrupted_completed_iterations(self):
        full = Solver(Config(iterations=6, seed=41, max_infosets=100_000))
        full.train()

        split = Solver(Config(iterations=2, seed=41, max_infosets=100_000))
        split.train()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(split, path)
            resumed, round_index, _ = load_checkpoint(path)
            self.assertEqual(round_index, 0)
            resumed.train(additional_iterations=4)

        self.assertEqual(full.deterministic_state(), resumed.deterministic_state())

    def test_corrupt_current_recovers_previous_and_never_rotates_corruption(self):
        solver = Solver(Config(iterations=1, seed=7))
        solver.train()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(solver, path)
            first = path.read_bytes()
            solver.train(additional_iterations=1)
            save_checkpoint(solver, path)
            previous = path.with_name("checkpoint.previous.json")
            self.assertEqual(previous.read_bytes(), first)

            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["solver"]["nodes"] += 1
            path.write_text(json.dumps(envelope), encoding="utf-8")
            recovered, _, payload = load_checkpoint(path)
            self.assertEqual(recovered.completed_iterations, 1)
            self.assertEqual(payload["_loaded_from"], str(previous))

            previous_before = previous.read_bytes()
            save_checkpoint(solver, path)
            self.assertEqual(previous.read_bytes(), previous_before)
            loaded, _, _ = load_checkpoint(path)
            self.assertEqual(loaded.completed_iterations, 2)

    def test_corrupt_only_generation_still_fails(self):
        solver = Solver(Config(iterations=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(solver, path)
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["solver"]["nodes"] = 1
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                load_checkpoint(path)

    def test_infoset_guard_rolls_back_partial_iteration_and_rng(self):
        solver = Solver(Config(iterations=2, seed=11, max_infosets=1))
        initial_rng = solver.rng.getstate()

        metadata = solver.train()

        self.assertEqual(metadata["stop_reason"], "max_infosets")
        self.assertEqual(solver.completed_iterations, 0)
        self.assertEqual(solver.completed_traversals, 0)
        self.assertEqual(solver.infosets, {})
        self.assertEqual(solver.rng.getstate(), initial_rng)

    def test_rehashed_wrong_abstraction_still_fails_game_fingerprint(self):
        solver = Solver(Config(iterations=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(solver, path)
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["config"]["hand_abstraction"] = "exact"
            envelope["sha256"] = _digest(envelope["payload"])
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                load_checkpoint(path)

    def test_semantic_source_hash_mismatch_is_rejected(self):
        solver = Solver(Config(iterations=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(solver, path)
            with patch(
                "plo_chipev.checkpoint.source_hashes",
                return_value={"changed.py": "not-the-saved-hash"},
            ), self.assertRaisesRegex(ValueError, "source hashes"):
                load_checkpoint(path)

    def test_disk_guard_runs_before_creating_checkpoint(self):
        solver = Solver(Config(iterations=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            with patch(
                "plo_chipev.checkpoint.shutil.disk_usage",
                return_value=SimpleNamespace(free=0),
            ), self.assertRaisesRegex(OSError, "free disk"):
                save_checkpoint(solver, path)
            self.assertFalse(path.exists())

    def test_round_ledger_survives_checkpoint_fallback_and_burns_reservations(self):
        solver = Solver(Config(iterations=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(solver, path, evaluation_round=0)
            initialize_round_ledger(path)
            first = reserve_evaluation_round(path, checkpoint_round=0)
            save_checkpoint(solver, path, evaluation_round=first)

            # This reservation is deliberately never mirrored to the checkpoint.
            self.assertEqual(reserve_evaluation_round(path, checkpoint_round=first), 2)
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["solver"]["nodes"] += 1
            path.write_text(json.dumps(envelope), encoding="utf-8")

            _, recovered_round, payload = load_checkpoint(path)
            self.assertIn("_recovered_current_error", payload)
            self.assertLess(recovered_round, 2)
            self.assertEqual(
                reserve_evaluation_round(path, checkpoint_round=recovered_round), 3
            )
            self.assertEqual(load_round_high_water(path), 3)

    def test_missing_or_corrupt_round_ledger_fails_closed_for_certification(self):
        solver = Solver(Config(iterations=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(solver, path)
            with self.assertRaisesRegex(ValueError, "round ledger"):
                reserve_evaluation_round(path, checkpoint_round=0)

            initialize_round_ledger(path)
            round_ledger_path(path).write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "round ledger"):
                reserve_evaluation_round(path, checkpoint_round=0)
