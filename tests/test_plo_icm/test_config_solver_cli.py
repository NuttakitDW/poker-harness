import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np

from plo_icm.config import Config, ConfigError, sunday_classic_mini
from plo_icm.cli import main
from plo_icm.solver import Solver, UnseenInformationSet


class ConfigTest(unittest.TestCase):
    def test_sunday_prizes_truncate_after_cashing(self):
        cfg = sunday_classic_mini(players_remaining=60)
        self.assertEqual(len(cfg.payouts), 60)
        self.assertEqual(cfg.payouts[-1], 54.34)

    def test_rejects_missing_ante_choice_and_bad_spot(self):
        base = dict(stacks=[10] * 6, payouts=[100, 50], players_remaining=6,
                    outside_stack=10, iterations=1)
        with self.assertRaises(ConfigError):
            Config.from_dict(base)
        with self.assertRaises(ConfigError):
            Config.from_dict({**base, "ante": .1, "ante_mode": "wat"})
        for field, bad in (("players_remaining", 6.5), ("iterations", True),
                           ("max_nodes", float("nan")), ("time_limit", float("nan")),
                           ("ante", True), ("outside_stack", True), ("averaging_epsilon", True)):
            with self.subTest(field=field), self.assertRaises(ConfigError):
                Config.from_dict({**base, "players_remaining": 6, "ante": .1,
                                  "ante_mode": "individual", field: bad})

    def test_equal_stack_icm_and_wta_dollar_linearity(self):
        cfg = Config.from_dict(dict(stacks=[10] * 6, payouts=[600], players_remaining=6,
                                    outside_stack=10, ante=.1, ante_mode="individual", iterations=1))
        solver = Solver(cfg)
        np.testing.assert_allclose(solver.terminal_utilities(np.array([[10] * 6])), [[100] * 6])

    def test_equal_stack_icm_allocates_custom_prize_pool(self):
        cfg = Config.from_dict(dict(stacks=[10] * 6, payouts=[300, 180, 120], players_remaining=6,
                                    outside_stack=10, ante=.1, ante_mode="individual", iterations=1))
        got = Solver(cfg).terminal_utilities(np.array([[10] * 6]))[0]
        np.testing.assert_allclose(got, [100] * 6)


class SolverTest(unittest.TestCase):
    def test_seed_reproducible_finite_strategy_and_unseen_error(self):
        data = dict(stacks=[3] * 6, payouts=[60], players_remaining=6, outside_stack=3,
                    ante=.1, ante_mode="individual", iterations=2, seed=7, max_nodes=1000)
        a, b = Solver(Config.from_dict(data)), Solver(Config.from_dict(data))
        a.train(); b.train()
        self.assertEqual(a.to_dict()["infosets"], b.to_dict()["infosets"])
        self.assertTrue(all(np.isfinite(x) for i in a.infosets.values() for x in i.strategy()))
        with self.assertRaises(UnseenInformationSet):
            a.query(0, "AsKsQdJd", ())

    def test_cli_custom_solve_and_query_unseen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, model = root / "c.json", root / "m.json"
            config.write_text(json.dumps(dict(stacks=[2] * 6, payouts=[60], players_remaining=6,
                outside_stack=2, ante=.1, ante_mode="individual", iterations=1, seed=2,
                max_nodes=100)))
            p = subprocess.run([sys.executable, "-m", "plo_icm", "solve", str(config), "-o", str(model)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            result = json.loads(p.stdout)
            self.assertIn(result["stop_reason"], ("iterations", "max_nodes"))
            q = subprocess.run([sys.executable, "-m", "plo_icm", "query", str(model),
                                "--seat", "0", "--hand", "AsKsQdJd"], capture_output=True, text=True)
            self.assertNotEqual(q.returncode, 0)
            self.assertIn("unavailable", q.stderr.lower())

    def test_cli_direct_preset_solve_export_and_supported_query(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, model, export = root / "c.json", root / "m.json", root / "e.json"
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["preset", "-o", str(config), "--stack", "2", "--players", "6",
                                       "--iterations", "1", "--max-nodes", "10000"]), 0)
            with redirect_stdout(out):
                self.assertEqual(main(["solve", str(config), "-o", str(model)]), 0)
            with redirect_stdout(out):
                self.assertEqual(main(["export", str(model), "-o", str(export)]), 0)
            exported = json.loads(export.read_text())
            self.assertIn("Sparse", exported["warning"])
            if exported["preflop"]:
                row = exported["preflop"][0]
                with redirect_stdout(out):
                    self.assertEqual(main(["query", str(model), "--seat", str(row["seat"]),
                                           "--hand", row["hand"]]), 0)
            err = StringIO()
            with redirect_stderr(err):
                self.assertEqual(main(["solve", str(root / "missing.json"), "-o", str(model)]), 2)

    def test_load_rejects_bad_infoset_key_and_training_counter(self):
        cfg = Config.from_dict(dict(stacks=[2] * 6, payouts=[60], players_remaining=6,
            outside_stack=2, ante=.1, ante_mode="individual", iterations=0))
        solver = Solver(cfg)
        data = solver.to_dict()
        data["infosets"] = {"[]": {"actions": ["check"], "regrets": [0],
                                     "strategy_sum": [1], "visits": 1}}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "infoset"):
                Solver.load(path)
            data["infosets"] = {}
            data["metadata"]["nodes"] = None
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "counter"):
                Solver.load(path)

    def test_old_action_schema_model_fails_clearly(self):
        cfg = Config.from_dict(dict(stacks=[2] * 6, payouts=[60], players_remaining=6,
            outside_stack=2, ante=.1, ante_mode="individual", iterations=0))
        data = Solver(cfg).to_dict()
        data["format"] = "plo-icm-mccfr-v1"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "action schema"):
                Solver.load(path)


if __name__ == "__main__":
    unittest.main()
