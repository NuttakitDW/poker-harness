import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).resolve().parents[2] / "research" / "plo_icm_archetypes" / "run_study.py"
SPEC = importlib.util.spec_from_file_location("plo_icm_study_runner", PATH)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


class ResearchRunnerTest(unittest.TestCase):
    def test_frozen_cohort_tiers_and_grid_size(self):
        runner.validate_cohort()
        self.assertEqual(len(runner.cells()), 8 * 5 * 2 * 3)
        self.assertEqual(len(runner.cells("pilot")), 4)
        self.assertEqual(len(runner.cells("sensitivity")), 12)
        self.assertEqual({row[2] for row in runner.COHORT},
                         {"Premium", "Speculative", "Marginal", "Trash"})

    def test_manifest_prevents_mixing_incompatible_runs(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            first = runner._manifest(5000, 128, 60, 3600, True)
            runner._prepare(output, first)
            runner._prepare(output, first)
            changed = dict(first, max_nodes=6000)
            with self.assertRaisesRegex(RuntimeError, "manifest differs"):
                runner._prepare(output, changed)

    def test_summary_uses_only_complete_cells(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            manifest = runner._manifest(5000, 128, 60, 3600, True)
            runner._prepare(output, manifest)
            cells = output / "cells"
            cells.mkdir()
            first, second = runner.cells("pilot")[:2]
            def identity(cell):
                hand_id, cards, tier, position, remaining, seed = cell
                config = runner.sunday_classic_mini(
                    players_remaining=remaining, stack=10, ante=.1, ante_mode="individual",
                    iterations=1_000_000, seed=seed, time_limit=60, max_nodes=5000,
                    max_infosets=100_000, opening_raise_mode="two_bb_only").to_dict()
                return {"cell_id": runner._cell_id(cell), "hand_id": hand_id, "cards": cards,
                        "tier": tier, "position": position, "players_remaining": remaining,
                        "seed": seed, "source_sha256": manifest["source_sha256"],
                        "eval_attempts_requested": 128, "config": config}
            complete = {"cell_id": runner._cell_id(first), "status": "complete", "tier": "Premium",
                        "cards": "AsAhKsKh", "position": "BTN", "players_remaining": 76,
                        "seed": 17, "selected_action": "raise_2bb", "complete_paired_samples": 8,
                        "effective_sample_size": 7, "uniform_fallback_fraction": .5,
                        "wall_seconds": 1, **identity(first)}
            error = {"status": "error", **identity(second)}
            (cells / f"{runner._cell_id(first)}.json").write_text(json.dumps(complete))
            (cells / f"{runner._cell_id(second)}.json").write_text(json.dumps(error))
            summary = runner.summarize(output)
            self.assertEqual((summary["cells_found"], summary["complete"]), (2, 1))
            csv_text = (output / "tables" / "completed_cells.csv").read_text()
            self.assertIn(runner._cell_id(first), csv_text)
            self.assertIn(runner._cell_id(second), csv_text)


if __name__ == "__main__":
    unittest.main()
