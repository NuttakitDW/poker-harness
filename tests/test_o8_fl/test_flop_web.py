from __future__ import annotations

import base64
import gzip
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from o8_fl import flop_web
from o8_fl.buckets import HANDS, Abstraction
from o8_fl.flop_web import _hands, build_library, export_strategy, post_nodes
from o8_fl.pool import DealPool
from o8_fl.strength import COUNTS, board_buckets
from o8_fl.trainer import Trainer
from o8_fl.tree import PublicTree
from plo_premium_proof.tables import comb_table, five_card_ranks

ROOT = Path(__file__).resolve().parents[2]


class FlopWebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.abstraction = Abstraction.build(samples=20_000)
        cls.tree = PublicTree.build()

    def test_post_nodes_follow_every_preflop_line_to_the_river(self) -> None:
        nodes, roots, _ = post_nodes(self.tree)
        self.assertEqual(set(roots), {"ck", "rc", "rrc", "rrrc", "rrrrc", "crc", "crrc", "crrrc", "crrrrc"})
        for root in roots.values():
            self.assertEqual(nodes[root]["actor"], 1)  # the big blind acts first after the flop
        self.assertEqual({n["street"] for n in nodes}, {1, 2, 3})
        root = nodes[roots["rc"]]
        self.assertEqual([o["action"] for o in root["options"]], ["check", "raise"])
        self.assertEqual(root["pot"], 4.0)
        facing = nodes[root["options"][1]["child"]]  # button facing a 1bb flop bet
        self.assertEqual([(o["action"], o["total"]) for o in facing["options"]],
                         [("fold", 0.0), ("call", 1.0), ("raise", 2.0)])
        self.assertEqual(nodes[facing["options"][1]["child"]]["street"], 2)  # calling closes the flop
        for node in nodes:
            for option in node["options"]:
                self.assertTrue(option["child"] >= 0 or option["end"] in ("showdown", "hand over"))

    def test_library_files_decode_to_one_bucket_per_hand_and_resume(self) -> None:
        calls = []

        def fake(hands, board, street, rank5, comb):
            calls.append(street)
            return np.zeros(len(hands), dtype=np.uint16)

        with tempfile.TemporaryDirectory() as d, patch.object(flop_web, "board_buckets", fake), \
                patch.object(flop_web, "ALL_FLOPS", 48):
            out = Path(d)
            index = build_library(out, self.abstraction)
            build_library(out, self.abstraction)
            self.assertEqual(len(calls), 48)  # the second run found every file
            self.assertEqual(json.loads((out / "o8-flops.json").read_text()), index)
            raw = gzip.decompress((out / f"flop-{index[0]['id']}.bin").read_bytes())
            self.assertEqual(len(np.frombuffer(raw, dtype="<u2")), HANDS)

    def test_strategy_export_sizes_each_street(self) -> None:
        rng = np.random.default_rng(0)
        cards = np.array([rng.permutation(52)[:13] for _ in range(50)], dtype=np.uint8)
        buckets = np.stack([rng.integers(0, k, size=(50, 2)) for k in COUNTS], axis=2).astype(np.uint16)
        pool = DealPool(cards, buckets, tuple(np.zeros((k, 1), dtype=np.float32) for k in COUNTS))
        trainer = Trainer(self.tree, self.abstraction, pool)
        trainer.run(500, threads=1, seed=1)
        with tempfile.TemporaryDirectory() as d:
            data = export_strategy(trainer, Path(d))
        blob = base64.b64decode(data["strategy"])
        self.assertEqual(len(blob), sum(COUNTS[n["street"] - 1] * 3 for n in data["nodes"]))
        self.assertEqual(data["buckets"], list(COUNTS))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BrowserRiverTest(unittest.TestCase):
    def test_browser_river_buckets_match_strength_buckets(self) -> None:
        abstraction = Abstraction.cached(ROOT / "tmp" / "o8_fl" / "abstraction.npz") \
            if (ROOT / "tmp" / "o8_fl" / "abstraction.npz").exists() else None
        if abstraction is None:
            self.skipTest("needs the cached O8 abstraction")
        board = [48, 1, 22, 26, 31]  # As 2d 7h 8h 9s
        expected = board_buckets(_hands(abstraction), np.asarray(board, dtype=np.int64), 3, five_card_ranks(), comb_table())
        script = f"""
            const R = require({json.dumps(str(ROOT / "public" / "static" / "plo-river.js"))});
            const rows = JSON.parse(require("fs").readFileSync({json.dumps(str(ROOT / "public" / "static" / "o8-classes.json"))})).rows;
            const order = R.comboOrder(rows.map(r => r[0].match(/../g)));
            process.stdout.write(Buffer.from(R.buckets(order, {json.dumps(board)}, {{ low: true }}).buffer));
        """
        out = subprocess.run(["node", "-e", script], capture_output=True, check=True, timeout=120).stdout
        np.testing.assert_array_equal(np.frombuffer(out, dtype="<u2"), expected)


if __name__ == "__main__":
    unittest.main()
