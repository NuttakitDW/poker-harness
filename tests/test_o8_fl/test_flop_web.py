from __future__ import annotations

import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from o8_fl import flop_web
from o8_fl.buckets import HANDS, Abstraction
from o8_fl.flop_web import build_library, export_strategy, flop_nodes
from o8_fl.pool import DealPool
from o8_fl.trainer import Trainer
from o8_fl.tree import PublicTree


class FlopWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.abstraction = Abstraction.build(samples=20_000)
        cls.tree = PublicTree.build()

    def test_flop_roots_follow_every_preflop_line_that_sees_a_flop(self) -> None:
        nodes, roots, _ = flop_nodes(self.tree)
        self.assertEqual(set(roots), {"ck", "rc", "rrc", "rrrc", "rrrrc", "crc", "crrc", "crrrc", "crrrrc"})
        for history, root in roots.items():
            self.assertEqual(nodes[root]["actor"], 1)  # the big blind acts first after the flop
        root = nodes[roots["rc"]]
        self.assertEqual([o["action"] for o in root["options"]], ["check", "raise"])
        self.assertEqual(root["pot"], 4.0)
        facing = nodes[root["options"][1]["child"]]  # button facing a 1bb flop bet
        self.assertEqual([(o["action"], o["total"]) for o in facing["options"]],
                         [("fold", 0.0), ("call", 1.0), ("raise", 2.0)])
        self.assertEqual(facing["options"][1]["end"], "turn")

    def test_library_files_decode_to_one_bucket_per_hand_and_resume(self) -> None:
        calls = []

        def fake(flop, centroids, order, cdf, seed=0):
            calls.append(seed)
            return np.zeros(len(order), dtype=np.uint16)

        with tempfile.TemporaryDirectory() as d, patch.object(flop_web, "flop_buckets", fake):
            out = Path(d)
            cdf = np.ones(1)
            index = build_library(48, out, self.abstraction, np.zeros((3, 3), dtype=np.float32), cdf)
            build_library(48, out, self.abstraction, np.zeros((3, 3), dtype=np.float32), cdf)
            self.assertEqual(len(calls), 48)  # second run found every file
            listed = json.loads((out / "o8-flops.json").read_text())
            self.assertEqual(listed, index)
            raw = gzip.decompress((out / f"o8-flop-{index[0]['id']}.bin").read_bytes())
            self.assertEqual(len(np.frombuffer(raw, dtype="<u2")), HANDS)

    def test_strategy_export(self) -> None:
        rng = np.random.default_rng(0)
        pool = DealPool(np.array([rng.permutation(52)[:13] for _ in range(50)], dtype=np.uint8),
                        rng.integers(0, 4, size=(50, 2, 3)).astype(np.uint16),
                        tuple(np.zeros((k, 3), dtype=np.float32) for k in (4, 4, 4)))
        trainer = Trainer(self.tree, self.abstraction, pool)
        trainer.run(500, threads=1, seed=1)
        with tempfile.TemporaryDirectory() as d:
            data = export_strategy(trainer, Path(d))
        blob = base64.b64decode(data["strategy"])
        self.assertEqual(len(blob), len(data["nodes"]) * 4 * 3)
        self.assertEqual(data["buckets"], 4)


if __name__ == "__main__":
    unittest.main()
