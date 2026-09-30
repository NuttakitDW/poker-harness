from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from plo_chipev_fast.cli import main


class CliTest(unittest.TestCase):
    def test_fresh_zero_iteration_training_writes_valid_checkpoint_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fast"
            result = main(
                [
                    "train",
                    "--output",
                    str(output),
                    "--iterations",
                    "0",
                    "--chance-seed",
                    "11",
                    "--sampling-seed",
                    "12",
                ]
            )
            self.assertEqual(result, 0)
            status = json.loads((output / "status.json").read_text())
            self.assertEqual(status["iterations_completed"], 0)
            self.assertEqual(status["stop_reason"], "iterations")
            self.assertTrue((output / "checkpoint.json").exists())

    def test_existing_output_requires_resume_or_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fast"
            self.assertEqual(
                main(["train", "--output", str(output), "--iterations", "0"]), 0
            )
            with self.assertRaisesRegex(ValueError, "resume|overwrite"):
                main(["train", "--output", str(output), "--iterations", "0"])

