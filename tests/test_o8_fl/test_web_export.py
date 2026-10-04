from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from o8_fl.buckets import PREFLOP_CLASSES, Abstraction
from o8_fl.cards import card_ids
from o8_fl.trainer import Trainer
from o8_fl.tree import PublicTree
from o8_fl.web_export import export, low_group


class WebExportTest(unittest.TestCase):
    def test_low_groups(self) -> None:
        self.assertEqual([low_group(h) for h in ("AsKh2d9c", "AsKh3d9c", "AsKh5d9c", "7s6h5d4c", "KsKhQdJc")],
                         [0, 1, 2, 3, 4])

    def test_export_matches_the_explorer_format(self) -> None:
        abstraction = Abstraction.build(samples=20_000)
        trainer = Trainer(PublicTree.build(), abstraction)
        trainer.run(2000, threads=1, seed=3)
        with tempfile.TemporaryDirectory() as d:
            export(trainer, abstraction, Path(d))
            game = json.loads((Path(d) / "o8-hu.json").read_text())
            classes = json.loads((Path(d) / "o8-classes.json").read_text())
        self.assertEqual(len(classes["rows"]), PREFLOP_CLASSES)
        self.assertEqual(game["buckets"], PREFLOP_CLASSES)
        self.assertEqual(len(game["nodes"]), 10)  # preflop decisions at a 5-bet cap
        blob = base64.b64decode(game["strategy"])
        self.assertEqual(len(blob), len(game["nodes"]) * PREFLOP_CLASSES * 3)
        root = game["nodes"][0]
        self.assertEqual([o["action"] for o in root["options"]], ["fold", "call", "raise"])
        self.assertEqual(root["options"][1]["total"], 1.0)  # completing the blind reads as a limp
        self.assertEqual(root["options"][0]["end"], "hand over")
        limp = game["nodes"][root["options"][1]["child"]]
        self.assertEqual([o["action"] for o in limp["options"]], ["check", "raise"])
        self.assertEqual(limp["options"][0]["end"], "flop")
        # The row of a class equals the trained policy, quantised to 1/255.
        c = abstraction.preflop_class(card_ids("AsAh3s2h"))
        row = blob[c * 3:c * 3 + 3]
        policy = trainer.average_policy(0, c)
        for got, want in zip(row, policy):
            self.assertLessEqual(abs(got / 255 - want), 1 / 255)


if __name__ == "__main__":
    unittest.main()
