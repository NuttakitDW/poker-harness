from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from plo_chipev_fast.checkpoint import load_checkpoint, save_checkpoint
from plo_chipev_fast.hands import HandLookup
from plo_chipev_fast.model import DenseModel
from plo_chipev_fast.trainer import FastTrainer
from plo_chipev_fast.tree import PublicTree


class CheckpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = PublicTree.build()
        cls.hands = HandLookup.build()

    def test_corrupt_current_falls_back_to_previous_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trainer = FastTrainer(
                DenseModel.empty(self.tree, self.hands), chance_seed=1, sampling_seed=2
            )
            save_checkpoint(trainer, root, overwrite=True)
            trainer.train(iterations=1)
            save_checkpoint(trainer, root)
            current = json.loads((root / "checkpoint.json").read_text())
            (root / current["payload"]["data_file"]).write_bytes(b"corrupt")
            recovered, metadata = load_checkpoint(root, self.tree, self.hands)
            self.assertEqual(recovered.completed_iterations, 0)
            self.assertEqual(metadata["loaded_generation"], "previous")
            previous_before = (root / "checkpoint.previous.json").read_bytes()
            recovered.train(iterations=1)
            save_checkpoint(recovered, root)
            loaded, metadata = load_checkpoint(root, self.tree, self.hands)
            self.assertEqual(loaded.completed_iterations, 1)
            self.assertEqual(metadata["loaded_generation"], "current")
            self.assertEqual(
                (root / "checkpoint.previous.json").read_bytes(), previous_before
            )
            self.assertLessEqual(len(list(root.glob("generation-*.npz"))), 2)

    def test_hash_mismatch_and_nonfinite_arrays_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trainer = FastTrainer(
                DenseModel.empty(self.tree, self.hands), chance_seed=1, sampling_seed=2
            )
            save_checkpoint(trainer, root, overwrite=True)
            with patch(
                "plo_chipev_fast.checkpoint.representation_hash", return_value="different"
            ), self.assertRaisesRegex(ValueError, "representation"):
                load_checkpoint(root, self.tree, self.hands)

        model = DenseModel.empty(self.tree, self.hands)
        model.regrets[0, 0, 0] = np.nan
        trainer = FastTrainer(model, chance_seed=1, sampling_seed=2)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            ValueError, "finite"
        ):
            save_checkpoint(trainer, Path(directory), overwrite=True)

    def test_disk_guard_precedes_write(self) -> None:
        trainer = FastTrainer(
            DenseModel.empty(self.tree, self.hands), chance_seed=1, sampling_seed=2
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "plo_chipev_fast.checkpoint.shutil.disk_usage",
            return_value=type("Usage", (), {"free": 1})(),
        ):
            with self.assertRaisesRegex(OSError, "disk"):
                save_checkpoint(trainer, Path(directory), overwrite=True)
            self.assertFalse((Path(directory) / "checkpoint.json").exists())

    def test_manifest_checksum_and_strict_trainer_schema_reject_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trainer = FastTrainer(
                DenseModel.empty(self.tree, self.hands), chance_seed=1, sampling_seed=2
            )
            save_checkpoint(trainer, root, overwrite=True)
            path = root / "checkpoint.json"
            envelope = json.loads(path.read_text())
            envelope["payload"]["trainer"]["chance_state"] = 999
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest SHA256"):
                load_checkpoint(root, self.tree, self.hands)

        state = trainer.state_dict()
        invalid_states = []
        for field, value in (
            ("iterations_completed", True),
            ("nodes", -1),
            ("active_training_seconds", math.inf),
            ("wall_seconds", -1.0),
            ("sampling_state", 1 << 64),
            ("stop_reason", 4),
        ):
            malformed = dict(state)
            malformed[field] = value
            invalid_states.append(malformed)
        malformed = dict(state)
        malformed["unknown"] = 1
        invalid_states.append(malformed)
        for malformed in invalid_states:
            with self.subTest(malformed=malformed), self.assertRaises(
                (TypeError, ValueError)
            ):
                FastTrainer.from_state(trainer.model, malformed)

    def test_explicit_overwrite_failure_preserves_old_valid_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trainer = FastTrainer(
                DenseModel.empty(self.tree, self.hands), chance_seed=1, sampling_seed=2
            )
            save_checkpoint(trainer, root, overwrite=True)
            old_manifest = (root / "checkpoint.json").read_bytes()
            with patch(
                "plo_chipev_fast.checkpoint.np.savez_compressed",
                side_effect=OSError("injected NPZ failure"),
            ), self.assertRaisesRegex(OSError, "injected"):
                save_checkpoint(trainer, root, overwrite=True)
            self.assertEqual((root / "checkpoint.json").read_bytes(), old_manifest)
            loaded, metadata = load_checkpoint(root, self.tree, self.hands)
            self.assertEqual(loaded.completed_iterations, 0)
            self.assertEqual(metadata["loaded_generation"], "current")
            with patch(
                "plo_chipev_fast.checkpoint._atomic_json",
                side_effect=OSError("injected manifest write failure"),
            ), self.assertRaisesRegex(OSError, "manifest write"):
                save_checkpoint(trainer, root, overwrite=True)
            self.assertEqual((root / "checkpoint.json").read_bytes(), old_manifest)
            loaded, _ = load_checkpoint(root, self.tree, self.hands)
            self.assertEqual(loaded.completed_iterations, 0)

    def test_managed_generation_cleanup_is_bounded_and_preserves_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unrelated = root / "keep-me.npz"
            unrelated.write_bytes(b"unrelated")
            trainer = FastTrainer(
                DenseModel.empty(self.tree, self.hands), chance_seed=1, sampling_seed=2
            )
            for _ in range(4):
                save_checkpoint(trainer, root, overwrite=not (root / "checkpoint.json").exists())
                trainer.train(iterations=1)
            managed = list(root.glob("generation-*.npz"))
            self.assertLessEqual(len(managed), 2)
            self.assertEqual(unrelated.read_bytes(), b"unrelated")
            current = json.loads((root / "checkpoint.json").read_text())["payload"]
            previous = json.loads((root / "checkpoint.previous.json").read_text())["payload"]
            self.assertEqual(
                {path.name for path in managed},
                {current["data_file"], previous["data_file"]},
            )
