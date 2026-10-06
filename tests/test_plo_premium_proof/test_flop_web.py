"""The PLO4 page's postflop data: bucket tables per board, the postflop tree, and the browser river buckets."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

import numpy as np

from plo_premium_proof.flop_web import LETTER, NO_BUCKET, class_order, flop_buckets, parse_board, post_tree, street_buckets
from plo_premium_proof.fullsolve import tree_config
from plo_premium_proof.fulltree import STREET_BUCKETS, FullTree
from plo_premium_proof.tables import comb_table, five_card_ranks


class FlopWebTest(unittest.TestCase):
    def test_board_cards_have_no_bucket_and_the_rest_fit_the_flop_buckets(self) -> None:
        board = parse_board("AsKd7c")
        hands = np.asarray([[48, 49, 50, 51], [20, 0, 1, 2], [16, 17, 18, 19]], dtype=np.int64)  # aces, 7c+deuces, sixes
        buckets = flop_buckets(hands, board, five_card_ranks(), comb_table())
        self.assertEqual(buckets[0], NO_BUCKET)
        self.assertEqual(buckets[1], NO_BUCKET)
        self.assertLess(buckets[2], STREET_BUCKETS[1])

    def test_postflop_tree_follows_heads_up_preflop_lines_to_the_river(self) -> None:
        config = tree_config(10.0, (4, 2, 2, 2), 0.116, seats=2, ante_on_top=True)
        tree = FullTree.build(config, cache_dir=None)
        nodes, roots, order = post_tree(tree, config.root())
        self.assertIn("ck", roots)  # SB limps, BB checks: the flop starts
        self.assertEqual(len(nodes), len(order))
        self.assertEqual({node["street"] for node in nodes}, {1, 2, 3})
        self.assertTrue(all(tree.street[node] == item["street"] for node, item in zip(order, nodes)))
        self.assertLessEqual(set("".join(roots)), set(LETTER.values()))
        for node in nodes:
            for option in node["options"]:
                self.assertTrue(option["child"] >= 0 or option["end"] in ("showdown", "hand over"))


RIVER_JS = Path(__file__).resolve().parents[2] / "public" / "static" / "plo-river.js"
CLASSES = Path(__file__).resolve().parents[2] / "public" / "static" / "plo-classes.json"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class BrowserRiverTest(unittest.TestCase):
    def test_browser_river_buckets_match_the_solver(self) -> None:
        board = parse_board("QhJh4c").tolist() + [9, 46]  # turn 4d, river Kh
        hands = class_order()
        expected = street_buckets(hands, np.asarray(board, dtype=np.int64), 3, five_card_ranks(), comb_table())
        script = f"""
            const R = require({json.dumps(str(RIVER_JS))});
            const rows = JSON.parse(require("fs").readFileSync({json.dumps(str(CLASSES))})).rows;
            const order = R.comboOrder(rows.map(r => r[0].match(/../g)));
            process.stdout.write(Buffer.from(R.buckets(order, {json.dumps(board)}).buffer));
        """
        out = subprocess.run(["node", "-e", script], capture_output=True, check=True, timeout=120).stdout
        np.testing.assert_array_equal(np.frombuffer(out, dtype="<u2"), expected)


if __name__ == "__main__":
    unittest.main()
