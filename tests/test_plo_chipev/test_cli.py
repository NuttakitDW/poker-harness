import argparse
import csv
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from plo_chipev.checkpoint import _digest, load_checkpoint, save_checkpoint
from plo_chipev.cli import _exclusive_lock, _positive_float, main
from plo_chipev.config import Config
from plo_chipev.solver import Solver


def minimal_report():
    positions = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
    return {
        "profile_hash": "placeholder",
        "overall_vpip": {"mean": 0.0},
        "table_hands": 1,
        "table_net_bb_per_100": 0.0,
        "by_position": {
            position: {"vpip": 0.0, "net_bb_per_100": 0.0}
            for position in positions
        },
        "hwang_inspired_reporting_only": {},
    }


class CLITest(unittest.TestCase):
    def test_positive_float_rejects_nonfinite_values(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                _positive_float(value)

    def test_train_resume_and_evaluate_create_usable_atomic_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            self.assertEqual(
                main([
                    "train", "--output", str(output), "--iterations", "1",
                    "--seed", "5", "--max-infosets", "10000",
                ]),
                0,
            )
            checkpoint = output / "checkpoint.json"
            self.assertTrue(checkpoint.exists())
            self.assertEqual(
                main([
                    "train", "--output", str(output), "--resume", str(checkpoint),
                    "--iterations", "1", "--max-infosets", "10000",
                ]),
                0,
            )
            report_path = output / "evaluation.json"
            self.assertEqual(
                main([
                    "evaluate", str(checkpoint), "--hands", "2", "--seed", "8",
                    "--output", str(report_path),
                ]),
                0,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["table_hands"], 2)
            self.assertFalse(report["certificate"]["certified"])
            self.assertTrue(report_path.with_suffix(".csv").exists())
            self.assertTrue((output / "checkpoint.previous.json").exists())

    def test_fresh_output_guard_and_nonblocking_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            command = [
                "train", "--output", str(output), "--iterations", "0",
                "--max-infosets", "10000",
            ]
            self.assertEqual(main(command), 0)
            self.assertEqual(main(command), 2)
            checkpoint = output / "checkpoint.json"
            with _exclusive_lock(checkpoint), self.assertRaisesRegex(
                RuntimeError, "locked"
            ), _exclusive_lock(checkpoint):
                pass

    def test_fresh_output_guard_runs_after_lock_acquisition(self):
        @contextmanager
        def delayed_lock(checkpoint):
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text("claimed-by-first-process", encoding="utf-8")
            yield

        commands = (
            lambda output: [
                "train",
                "--output",
                str(output),
                "--iterations",
                "0",
            ],
            lambda output: [
                "solve",
                "--output",
                str(output),
                "--max-seconds",
                "1",
            ],
        )
        for index, command in enumerate(commands):
            with self.subTest(command=index), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "run"
                with patch("plo_chipev.cli._exclusive_lock", new=delayed_lock), patch(
                    "plo_chipev.cli.save_checkpoint",
                    side_effect=AssertionError("freshness guard ran before lock"),
                ) as checkpoint_save:
                    self.assertEqual(main(command(output)), 2)
                checkpoint_save.assert_not_called()

    def test_tiny_solve_deadline_still_writes_a_valid_initial_checkpoint(self):
        clock = iter((0.0, 2.0, 2.0))
        with tempfile.TemporaryDirectory() as directory, patch(
            "plo_chipev.cli.time.perf_counter", side_effect=lambda: next(clock)
        ):
            output = Path(directory) / "solve"
            self.assertEqual(
                main(["solve", "--output", str(output), "--max-seconds", "1"]),
                0,
            )
            status = json.loads((output / "status.json").read_text())
            checkpoint = Path(status["checkpoint"])
            loaded, evaluation_round, _ = load_checkpoint(checkpoint)
            checkpoint_existed = checkpoint.exists()

        self.assertTrue(checkpoint_existed)
        self.assertEqual(loaded.completed_iterations, 0)
        self.assertEqual(evaluation_round, 0)
        self.assertEqual(status["checkpoint_identity"]["iterations_completed"], 0)

    def test_explicit_overwrite_replaces_source_incompatible_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            checkpoint = output / "checkpoint.json"
            save_checkpoint(Solver(Config(iterations=0)), checkpoint)
            envelope = json.loads(checkpoint.read_text(encoding="utf-8"))
            envelope["payload"]["source_hashes"] = {"obsolete.py": "old"}
            envelope["sha256"] = _digest(envelope["payload"])
            checkpoint.write_text(json.dumps(envelope), encoding="utf-8")
            unrelated = output / "keep-me.txt"
            unrelated.write_text("preserved", encoding="utf-8")

            self.assertEqual(
                main([
                    "train",
                    "--output",
                    str(output),
                    "--iterations",
                    "0",
                    "--overwrite",
                ]),
                0,
            )
            loaded, evaluation_round, _ = load_checkpoint(checkpoint)

            self.assertEqual(loaded.completed_iterations, 0)
            self.assertEqual(evaluation_round, 0)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "preserved")

    def test_certificate_round_is_reserved_before_interrupted_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            self.assertEqual(
                main(["train", "--output", str(output), "--iterations", "0"]), 0
            )
            checkpoint = output / "checkpoint.json"
            with patch(
                "plo_chipev.cli.certify_profile", side_effect=RuntimeError("interrupted")
            ):
                code = main([
                    "evaluate", str(checkpoint), "--hands", "1", "--seed", "4",
                    "--output", str(output / "report.json"),
                    "--certificate-batches", "2",
                ])
            self.assertEqual(code, 2)
            _, evaluation_round, _ = load_checkpoint(checkpoint)
            self.assertEqual(evaluation_round, 1)

    def test_solve_is_finite_and_never_certifies_an_incomplete_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "solve"
            code = main([
                "solve", "--output", str(output), "--max-seconds", "2",
                "--chunk-iterations", "1", "--chunk-seconds", "0.2",
                "--evaluation-hands", "1", "--certificate-batches", "2",
                "--certificate-batch-hands", "1", "--certificate-max-nodes", "1",
                "--max-nodes", "100000", "--max-infosets", "10000",
            ])
            self.assertEqual(code, 0)
            status = json.loads((output / "status.json").read_text())
            self.assertEqual(status["state"], "budget_limited")
            self.assertFalse(status["target_certified"])
            report = json.loads((output / "evaluation.json").read_text())
            self.assertFalse(report["certificate"]["complete"])
            self.assertFalse(report["certificate"]["certified"])

    def test_solve_marks_last_written_evaluation_stale_after_next_training_chunk(self):
        def train_one(solver, **_kwargs):
            solver.completed_iterations += 1
            solver.stop_reason = "iterations"
            return {"stop_reason": "iterations"}

        clock = iter([0.0] * 11 + [11.0, 11.0])
        with tempfile.TemporaryDirectory() as directory, patch(
            "plo_chipev.cli.time.perf_counter", side_effect=lambda: next(clock)
        ), patch("plo_chipev.cli.Solver.train", new=train_one), patch(
            "plo_chipev.cli.evaluate_profile",
            side_effect=lambda *_args, **_kwargs: minimal_report(),
        ), patch(
            "plo_chipev.cli.certify_profile",
            return_value={"complete": True, "certified": False},
        ):
            output = Path(directory) / "solve"
            self.assertEqual(
                main(["solve", "--output", str(output), "--max-seconds", "10"]),
                0,
            )
            status = json.loads((output / "status.json").read_text())
            report = json.loads((output / "evaluation.json").read_text())
            with (output / "evaluation.csv").open(newline="") as stream:
                csv_row = next(csv.DictReader(stream))

        self.assertTrue(status["evaluation_stale"])
        self.assertEqual(status["checkpoint_identity"]["iterations_completed"], 2)
        self.assertEqual(
            status["last_successfully_written_evaluation"]["iterations_completed"],
            1,
        )
        self.assertEqual(csv_row["report_id"], report["report_id"])

    def test_solve_does_not_advertise_behavior_report_that_missed_write_deadline(self):
        def train_one(solver, **_kwargs):
            solver.completed_iterations += 1
            solver.stop_reason = "iterations"
            return {"stop_reason": "iterations"}

        clock = iter([0.0] * 6 + [11.0, 11.0, 11.0])
        with tempfile.TemporaryDirectory() as directory, patch(
            "plo_chipev.cli.time.perf_counter", side_effect=lambda: next(clock)
        ), patch("plo_chipev.cli.Solver.train", new=train_one), patch(
            "plo_chipev.cli.evaluate_profile",
            side_effect=lambda *_args, **_kwargs: minimal_report(),
        ):
            output = Path(directory) / "solve"
            self.assertEqual(
                main(["solve", "--output", str(output), "--max-seconds", "10"]),
                0,
            )
            status = json.loads((output / "status.json").read_text())
            evaluation_exists = (output / "evaluation.json").exists()

        self.assertIsNone(status["evaluation"])
        self.assertIsNone(status["last_successfully_written_evaluation"])
        self.assertIsNone(status["evaluation_stale"])
        self.assertFalse(evaluation_exists)
