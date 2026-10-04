from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from o8_fl.buckets import PREFLOP_CLASSES, Abstraction
from o8_fl.cli import main


class CliTest(unittest.TestCase):
    def test_train_resumes_and_chart_lists_every_class(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            Abstraction.build(samples=20_000).save(root / "abs.npz")
            common = ["--run", str(root / "run"), "--abstraction", str(root / "abs.npz")]
            with redirect_stdout(io.StringIO()):
                # 2,000 is not a multiple of 3 threads: the leftover must not raise.
                main(common + ["train", "--iterations", "2000", "--threads", "3", "--checkpoint-every", "999"])
                main(common + ["train", "--iterations", "300", "--threads", "3"])
            lines = (root / "run" / "progress.jsonl").read_text().splitlines()
            self.assertEqual(json.loads(lines[-1])["iterations"], 2298)
            out = io.StringIO()
            with redirect_stdout(out):
                main(common + ["chart"])
            with open(root / "run" / "preflop.csv") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), PREFLOP_CLASSES)
            first = rows[0]
            total = sum(float(first[k]) for k in ("sb_open_fold", "sb_open_limp", "sb_open_raise"))
            self.assertAlmostEqual(total, 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
