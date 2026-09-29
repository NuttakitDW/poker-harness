import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).resolve().parents[2] / "research" / "plo_icm_archetypes" / "analyze_results.py"
SPEC = importlib.util.spec_from_file_location("plo_icm_analysis", PATH)
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(analysis)


class AnalyzeResultsTest(unittest.TestCase):
    def _study(self, root: Path):
        manifest = {"mode": "main", "cohort": [["aakk", "AsAhKsKh", "Premium"]],
                    "positions": ["BTN"], "stages": [76], "seeds": [17, 29, 43],
                    "source_sha256": "frozen", "eval_attempts": 8, "max_nodes": 10,
                    "timeout_seconds": 2, "opening_raise_mode": "two_bb_only"}
        (root / "cells").mkdir(parents=True)
        (root / "manifest.json").write_text(json.dumps(manifest))
        for seed, action in zip(manifest["seeds"], analysis.ACTIONS):
            ev = {"fold": 10 + seed / 100, "call": 11 + seed / 100,
                  "raise_2bb": 12 + seed / 100}
            row = {"cell_id": f"aakk__btn__left76__seed{seed}", "source_sha256": "frozen",
                   "hand_id": "aakk", "cards": "AsAhKsKh", "tier": "Premium",
                   "position": "BTN", "players_remaining": 76, "seed": seed,
                   "eval_attempts_requested": 8, "status": "complete", "selected_action": action,
                   "config": {"max_nodes": 10, "time_limit": 2,
                              "opening_raise_mode": "two_bb_only",
                              "players_remaining": 76, "seed": seed},
                   "action_ev_dollars": ev,
                   "pairwise_se_dollars": {"raise_2bb|call": .4, "call|fold": .3},
                   "uniform_fallback_fraction": .8, "effective_sample_size": 7}
            (root / "cells" / f"{row['cell_id']}.json").write_text(json.dumps(row))

    def test_split_votes_contrasts_and_diagnostic_figure(self):
        with tempfile.TemporaryDirectory() as td:
            main, output = Path(td) / "main", Path(td) / "out"
            self._study(main)
            result = analysis.analyze(main, output)
            self.assertEqual(result["main_status_counts"], {"complete": 3})
            csv_text = (output / "hand_position_stage_summary.csv").read_text()
            self.assertIn("split:call/fold/raise_2bb", csv_text)
            self.assertIn("raise_minus_limp_paired_se_mean", csv_text)
            completed = (output / "completed_cells.csv").read_text()
            self.assertIn("fold_ev_dollars", completed)
            self.assertIn("raise_minus_limp_paired_se_dollars", completed)
            self.assertNotIn("{'fold':", completed)
            svg = (output / "modal_actions_left76.svg").read_text()
            self.assertIn("not a strategy chart", svg)
            self.assertIn("Split (1/3; n=3/3)", svg)

    def test_foreign_cell_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            main = Path(td)
            self._study(main)
            row = json.loads(next((main / "cells").glob("*.json")).read_text())
            row["source_sha256"] = "changed"
            next((main / "cells").glob("*.json")).write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "manifest"):
                analysis._load(main)


if __name__ == "__main__":
    unittest.main()
