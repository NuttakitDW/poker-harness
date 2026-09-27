"""Checks the /method page: our push/fold chart against Jonathan Little's published chart."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "web"))
import method  # noqa: E402


class RangeTests(unittest.TestCase):
    def test_notation_expands_to_hand_classes(self):
        self.assertEqual(method.expand("44+"), {"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44"})
        self.assertEqual(method.expand("A8s+"), {"AKs", "AQs", "AJs", "ATs", "A9s", "A8s"})
        self.assertEqual(method.expand("A5s-A4s"), {"A5s", "A4s"})
        self.assertEqual(method.expand("KQo T9s"), {"KQo", "T9s"})
        self.assertEqual(len(method.expand("Ax")), 25)

    def test_every_published_percentage_is_reproduced(self):
        reference = method.load_reference()
        for stack, row in reference["ranges"].items():
            with self.subTest(stack=stack):
                self.assertAlmostEqual(method.percent(method.expand(row["range"])), row["percent"], delta=0.1)

    def test_the_grid_is_the_solver_hand_order(self):
        grid = method.GRID
        self.assertEqual((len(grid), grid[0], grid[1], grid[13], grid[14], grid[-1]),
                         (169, "AA", "AKs", "AKo", "KK", "22"))


class CompareTests(unittest.TestCase):
    def comparison(self, ours):
        freqs = {hand: 0.0 for hand in method.GRID}
        freqs.update(ours)
        return method.Comparison(stack=10, ours=freqs, theirs={"AA", "KK", "A8s"},
                                 gaps={hand: 0.0 for hand in method.GRID}, theirs_percent=1.2,
                                 exploitability=0.002, seconds=1.0)

    def test_a_hand_matches_when_our_main_action_is_theirs(self):
        result = self.comparison({"AA": 1.0, "KK": 0.5, "A8s": 0.36})
        self.assertEqual(result.differ, ["A8s"])
        self.assertEqual(result.matched, 168)

    def test_a_hand_only_we_shove_is_a_difference(self):
        self.assertIn("22", self.comparison({"AA": 1, "KK": 1, "A8s": 1, "22": 0.67}).differ)


class RenderTests(unittest.TestCase):
    def setUp(self):
        freqs = {hand: 0.0 for hand in method.GRID}
        freqs.update({"AA": 1.0, "KK": 1.0, "A8s": 0.36})
        main = method.Comparison(stack=10, ours=freqs, theirs={"AA", "KK", "A8s"},
                                 gaps={hand: 0.0 for hand in method.GRID}, theirs_percent=14.3,
                                 exploitability=0.002, seconds=1.3)
        self.html = method.render(main, [main], method.load_reference(), before_ante_matched=168)

    def test_the_page_has_both_grids_and_the_copyright(self):
        self.assertEqual(self.html.count('class="cell'), 2 * 169)
        self.assertIn("Copyright", self.html)
        self.assertNotIn("${", self.html)

    def test_the_page_cites_the_source(self):
        self.assertIn("https://pokercoaching.com/push-fold-charts/", self.html)
        self.assertIn("2026-09-27", self.html)

    def test_a_difference_is_listed_with_its_ev_gap(self):
        self.assertIn("A8s", self.html)
        self.assertIn("168/169", self.html)


class SummaryTests(unittest.TestCase):
    """The page's numbers are also saved for the chat AI, so both always say the same thing."""

    def test_the_summary_has_the_numbers_on_the_page(self):
        freqs = {hand: 0.0 for hand in method.GRID}
        freqs.update({"AA": 1.0, "KK": 1.0, "A8s": 0.36})
        gaps = {hand: 0.0 for hand in method.GRID}
        gaps["A8s"] = -0.035
        main = method.Comparison(stack=10, ours=freqs, theirs={"AA", "KK", "A8s"}, gaps=gaps,
                                 theirs_percent=14.3, exploitability=0.0007, seconds=1.3)
        summary = method.summary(main, [main], method.load_reference())
        self.assertEqual((summary["matched"], summary["total"], summary["differ"]), (168, 169, ["A8s"]))
        self.assertEqual(summary["widest"], {"hand": "A8s", "gap_bb": -0.035})
        self.assertEqual(summary["stacks"], {"from": 10, "to": 10, "matched_min": 168, "matched_max": 168})
        self.assertIn("Jonathan Little", summary["reference"])


if __name__ == "__main__":
    unittest.main()
