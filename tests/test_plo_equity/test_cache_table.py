import csv
import tempfile
import unittest
from pathlib import Path

from plo_equity.cache import Cache, CacheError, Metadata
from plo_equity.cards import enumerate_classes
from plo_equity.simulation import TrialStats
from plo_equity.table import export_tables, ranked_classes, weighted_summary


class CacheAndTableTest(unittest.TestCase):
    def test_metadata_rejects_non_integral_hu_count(self):
        for opponents in (True, 1.0):
            with self.subTest(opponents=opponents), self.assertRaises(TypeError):
                Metadata(global_seed=17, opponents=opponents)
        with self.assertRaises(ValueError):
            Metadata(global_seed=17, opponents=2)

    def test_metadata_is_strict_and_additions_are_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "equity.sqlite"
            meta = Metadata(global_seed=17, opponents=1)
            cache = Cache(path, meta)
            cache.add("00010203", 0, TrialStats(10, 5, 4.5, 4, 2))
            self.assertEqual(cache.load()["00010203"].n, 10)
            with self.assertRaises(CacheError):
                cache.add("00010203", 0, TrialStats(1, 1, 1, 1, 0))
            with self.assertRaisesRegex(CacheError, "HU moments"):
                cache.add("01020304", 0, TrialStats(10, 5, 5, 4, 2))
            cache.close()
            with self.assertRaisesRegex(CacheError, "metadata"):
                Cache(path, Metadata(global_seed=18, opponents=1))

    def test_exports_have_rank_uncertainty_and_all_physical_hands(self):
        classes = enumerate_classes()
        rows = {hand.key: TrialStats(10, 4 + (i % 3), 4 + (i % 3), 4 + (i % 3), 0)
                for i, hand in enumerate(classes)}
        with tempfile.TemporaryDirectory() as folder:
            class_csv = Path(folder) / "classes.csv"
            physical_csv = Path(folder) / "physical.csv"
            export_tables(rows, class_csv, physical_csv, Metadata(global_seed=17, opponents=1))
            with class_csv.open() as stream:
                class_rows = list(csv.DictReader(stream))
            self.assertEqual(len(class_rows), 16_432)
            self.assertIn("equity_standard_error", class_rows[0])
            self.assertIn("estimated_class_rank", class_rows[0])
            self.assertEqual(class_rows[0]["opponents"], "1")
            self.assertIn("source_fingerprint", class_rows[0])
            with physical_csv.open() as stream:
                self.assertEqual(sum(1 for _ in stream) - 1, 270_725)

    def test_weighted_mean_propagates_class_standard_errors(self):
        classes = enumerate_classes()
        rows = {hand.key: TrialStats(100, 50, 50, 50, 0) for hand in classes}
        summary = weighted_summary(rows)
        self.assertAlmostEqual(summary["weighted_equity"], .5)
        self.assertGreater(summary["propagated_standard_error"], 0)

    def test_equal_estimates_share_physical_midrank_and_percentile(self):
        classes = enumerate_classes()
        rows = {hand.key: TrialStats(100, 50, 50, 50, 0) for hand in classes}
        ranked = ranked_classes(rows)
        self.assertEqual({row["estimated_class_rank"] for row in ranked}, {(1 + 16_432) / 2})
        self.assertEqual({row["physical_weighted_percentile"] for row in ranked}, {50.0})
        self.assertEqual({row["estimated_physical_rank_start"] for row in ranked}, {1})
        self.assertEqual({row["estimated_physical_rank_end"] for row in ranked}, {270_725})

    def test_corrupt_statistics_are_rejected(self):
        for args in ((-1, 0, 0, 0, 0), (10, float("nan"), 1, 0, 0),
                     (10, 5, 2, 5, 0), (10, 5, 5, 9, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                TrialStats(*args)


if __name__ == "__main__":
    unittest.main()
