"""M6: compare with a published HU Nash chart, and hold invariants on random tables."""

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from pushfold import auditor, coach, hands  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

ROUNDING = 0.5  # published thresholds are to 0.1bb; a mixed hand may sit on either side


def published() -> dict[str, np.ndarray]:
    tables, current = {}, None
    for line in (HERE / "fixtures" / "hrc_hu_noante.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current = line[1:-1]
            tables[current] = []
            continue
        tables[current].append([99.0 if v == "20+" else np.nan if v == "*" else float(v)
                                for v in line.split()])
    return {k: np.array(v).ravel() for k, v in tables.items()}


class HeadsUpChartTest(unittest.TestCase):
    def test_matches_holdemresources_within_rounding(self):
        chart = published()
        for stack in (4, 6, 8, 10, 12, 15):
            result = coach.solve(Spot((stack, stack)), target=0.001)
            for name, seat, history in (("push", 0, None), ("call", 1, (1,))):
                ours = result.strategy[result.node(seat, history).index][:, 1]
                for i, limit in enumerate(chart[name]):
                    if np.isnan(limit) or (ours[i] > 0.5) == (limit >= stack):
                        continue
                    with self.subTest(stack=stack, hand=hands.CLASSES[i], table=name):
                        self.assertLess(abs(limit - stack), ROUNDING)


class RandomTableTest(unittest.TestCase):
    def test_random_tables_converge_and_stay_zero_sum(self):
        rng = np.random.default_rng(7)
        for _ in range(12):
            n = int(rng.integers(2, 7))
            spot = Spot(tuple(rng.uniform(2, 15, n).round(1)), ante=float(rng.choice([0, 0.1, 0.125])))
            result = coach.solve(spot, max_iters=5000)
            with self.subTest(spot=spot):
                self.assertLess(result.exploitability, 0.01)
                report = auditor.audit(result.tree, result.strategy)
                self.assertAlmostEqual(float(report.ev.sum()), 0.0, places=8)


if __name__ == "__main__":
    unittest.main()
