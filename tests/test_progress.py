from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "final_table"))

import mtt_batch  # noqa: E402
import progress  # noqa: E402

from plo_premium_proof.finaltable import FinalTableSpec  # noqa: E402

DEAD_PID = 2**22 + 12345  # above macOS/Linux pid limits: never a live process


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.folder.name)
        self.jobs = self.root / "jobs"

    def tearDown(self):
        self.folder.cleanup()

    def _batch(self, items, pid=None, state="running"):
        progress.write_json(self.root / "batch.json", {"name": "t", "pid": pid or os.getpid(), "started": 1000.0,
                                                       "state": state, "items": items})

    def test_no_batch(self):
        self.assertIsNone(progress.library(self.root / "batch.json", self.jobs))
        snap = progress.snapshot(self.root / "missing", self.jobs)
        self.assertIsNone(snap["library"])
        self.assertIsNone(snap["training"])
        self.assertGreater(snap["disk_free_gb"], 0)

    def test_counts_current_spot_and_time_left(self):
        self._batch([
            {"label": "a", "minutes": 10, "seats": 5, "state": "done", "job": "j1", "started": 1000, "finished": 1720},
            {"label": "b", "minutes": 18, "seats": 6, "state": "running", "job": "j2", "started": 1720},
            {"label": "c", "minutes": 18, "seats": 6, "state": "queued", "job": None},
            {"label": "d", "minutes": 10, "seats": 5, "state": "skipped", "job": None},
        ])
        progress.write_json(self.jobs / "j2" / "status.json",
                            {"state": "solving", "seconds": 480.0, "budget_seconds": 1080.0, "deals": 9_600_000})
        lib = progress.library(self.root / "batch.json", self.jobs, now=2300.0)
        self.assertEqual((lib["state"], lib["total"], lib["done"], lib["queued"]), ("running", 3, 1, 1))
        self.assertAlmostEqual(lib["overhead_minutes"], 2.0)          # 12 min taken for a 10 min budget
        self.assertEqual(lib["eta_seconds"], (18 + 2) * 60 + (1080 - 480))
        self.assertEqual(lib["current"]["label"], "b")
        self.assertEqual(lib["recent"][0]["label"], "a")
        self.assertEqual(lib["next"], ["c"])
        self.assertAlmostEqual(lib["finish_at"], 2300.0 + lib["eta_seconds"])

    def test_dead_runner_shows_interrupted(self):
        self._batch([{"label": "a", "minutes": 10, "state": "running", "job": "j1", "started": 1000}], pid=DEAD_PID)
        lib = progress.library(self.root / "batch.json", self.jobs, now=1100.0)
        self.assertEqual(lib["state"], "interrupted")
        self.assertEqual(lib["eta_seconds"], 0)
        self.assertIsNone(lib["current"])

    def test_training_passes_through_and_flags_a_dead_trainer(self):
        path = self.root / "training" / "status.json"
        progress.write_json(path, {"state": "running", "pid": os.getpid(), "epoch": 3, "epochs": 20,
                                   "train_loss": [0.3, 0.2, 0.1], "holdout_loss": [0.35, 0.25, 0.2]})
        self.assertEqual(progress.training(path)["epoch"], 3)
        progress.write_json(path, {"state": "running", "pid": DEAD_PID, "epoch": 3, "epochs": 20})
        self.assertEqual(progress.training(path)["state"], "interrupted")


class BatchRunnerTest(unittest.TestCase):
    def test_batch_file_tracks_each_spot(self):
        specs = [FinalTableSpec(stacks=(4.0, 2.5, 6.0), payouts=(50, 30, 20), minutes=1, label=f"spot {i}")
                 for i in range(2)]
        seen = []

        def fake_run(job, jobs):
            seen.append(json.loads((jobs.parent / "batch.json").read_text())["items"][len(seen)]["state"])
            progress.write_json(jobs / job / "status.json", {"state": "done"})

        with tempfile.TemporaryDirectory() as folder, mock.patch.object(mtt_batch, "run", fake_run), \
                mock.patch.object(mtt_batch.time, "strftime", side_effect=["20260101-000001", "20260101-000002"]):
            root = pathlib.Path(folder)
            batch = mtt_batch.run_batch(specs, root / "jobs", root / "batch.json", "test")
            saved = json.loads((root / "batch.json").read_text())
        self.assertEqual(seen, ["running", "running"])
        self.assertEqual(batch["state"], "done")
        self.assertEqual([i["state"] for i in saved["items"]], ["done", "done"])
        self.assertTrue(all(i["finished"] >= i["started"] for i in saved["items"]))


if __name__ == "__main__":
    unittest.main()
