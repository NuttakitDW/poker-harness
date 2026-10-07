from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import numpy as np

from o8_fl.exact import colex_table, features_from_sums, river_sums, river_sums_fast, strong_weights
from o8_fl.exact_tables import PERMS, cell_of, fit_grid, flop_maps, lookup
from o8_fl.flops import ALL_FLOPS, select_flops
from o8_fl.ranges import COMBOS

ROOT = Path(__file__).resolve().parents[2]
RANGE = ROOT / "tmp" / "o8_fl" / "strong_range.npz"


@unittest.skipUnless(RANGE.exists(), "needs the strong range")
class ExactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.colex = colex_table()
        cls.weights = strong_weights(RANGE)
        rng = np.random.default_rng(5)
        cls.hands = np.ascontiguousarray(COMBOS[rng.choice(len(COMBOS), 400, replace=False)])

    def test_fast_sums_equal_the_plain_sums(self) -> None:
        for board in ([48, 1, 22, 26, 31], [12, 13, 14, 40, 51], [0, 5, 10, 15, 20]):
            board = np.asarray(board, dtype=np.int64)
            fast = river_sums_fast(board, self.hands, self.weights, self.colex)
            np.testing.assert_array_equal(fast, river_sums(board, self.hands, self.weights, self.colex))

    def test_features_are_pot_shares(self) -> None:
        board = np.asarray([48, 1, 22, 26, 31], dtype=np.int64)
        f = features_from_sums(river_sums_fast(board, self.hands, self.weights, self.colex))
        live = f[f[:, 2] > 0]
        self.assertTrue(np.all(live[:, 0] >= 0) and np.all(live[:, 0] + live[:, 1] <= 1.0 + 1e-9))
        self.assertTrue(np.all(live[:, 1] <= 0.5 + 1e-9) and np.all(live[:, 4] <= 0.5 + 1e-9))

    def test_the_nuts_scoop(self) -> None:
        board = np.asarray([0, 5, 10, 31, 35], dtype=np.int64)   # 2c 3d 4h 9s Ts
        hand = np.asarray([[13, 18, 47, 48]], dtype=np.int64)    # 5d 6h Ks Ac: 6-high straight and the wheel
        f = features_from_sums(river_sums_fast(board, hand, self.weights, self.colex))[0]
        self.assertGreater(f[0] + f[1], 0.75)
        self.assertGreater(f[1], 0.4)


class GridTest(unittest.TestCase):
    def test_cells_and_lookup_follow_the_cut_points(self) -> None:
        rng = np.random.default_rng(0)
        points = rng.random((5000, 5))
        grid = fit_grid(points, 20, bins=(4, 4, 2, 2, 2), seed=0)
        bins = grid["bins"].astype(np.int64)
        cells = {cell_of(p, grid["edges"], bins) for p in points}
        self.assertLessEqual(max(cells), int(np.prod(bins)) - 1)
        out = lookup(points, np.ones(len(points), dtype=np.bool_), grid["edges"], bins, grid["table"])
        self.assertTrue(np.all(out < 20))

    def test_every_flop_maps_into_the_library(self) -> None:
        lib, perm = flop_maps()
        library = select_flops(ALL_FLOPS, 0)
        for a, b, c in ((0, 1, 2), (20, 33, 48), (5, 9, 50)):
            key = a * 2704 + b * 52 + c
            p = PERMS[perm[key]]
            mapped = tuple(sorted(int((x >> 2) * 4 + p[x & 3]) for x in (a, b, c)))
            self.assertEqual(mapped, tuple(library[lib[key]]))


@unittest.skipUnless(shutil.which("node") and RANGE.exists() and (ROOT / "tmp/o8_fl/exact/grids.npz").exists(),
                     "needs node and the fitted grids")
class BrowserRiverTest(unittest.TestCase):
    def test_o8_river_js_matches_python(self) -> None:
        import tempfile
        from o8_fl import exact_tables as E
        s = E._setup()
        grid = E.load_grids()[2]
        board = [48, 1, 22, 26, 31]
        sums = river_sums_fast(np.asarray(board, dtype=np.int64), s["hands"], s["weights"], s["colex"])
        means = np.full((len(sums), 5), np.nan)
        for k in range(len(sums)):
            E._river_features(sums, k, means[k])
        expected = E._bucket(grid, means, ~np.isnan(means[:, 0]))
        with tempfile.TemporaryDirectory() as d:
            E.export_river(Path(d))
            script = f"""
                const fs = require("fs"), zlib = require("zlib");
                const P = require({json.dumps(str(ROOT / "public/static/plo-river.js"))});
                const O = require({json.dumps(str(ROOT / "public/static/o8-river.js"))});
                const rows = JSON.parse(fs.readFileSync({json.dumps(str(ROOT / "public/static/o8-classes.json"))})).rows;
                const meta = JSON.parse(fs.readFileSync({json.dumps(d + "/o8-river-grid.json")}));
                const raw = zlib.gunzipSync(fs.readFileSync({json.dumps(d + "/o8-river-table.bin")}));
                O.setGrid({{bins: meta.bins, edges: meta.edges.map(e => Float64Array.from(e)),
                           weights: Float64Array.from(meta.weights),
                           table: new Uint16Array(raw.buffer, raw.byteOffset, raw.length / 2)}});
                const out = O.buckets(P.comboOrder(rows.map(r => r[0].match(/../g))), {json.dumps(board)});
                process.stdout.write(Buffer.from(out.buffer));
            """
            out = subprocess.run(["node", "-e", script], capture_output=True, check=True, timeout=300).stdout
        np.testing.assert_array_equal(np.frombuffer(out, dtype="<u2"), expected)


if __name__ == "__main__":
    unittest.main()
