from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from o8_fl import pool
from o8_fl.pool import DealPool, assign, build_pool, generate, generate_chunks, kmeans


class PoolTest(unittest.TestCase):
    def test_generate_shapes_and_ranges(self) -> None:
        cards, features = generate(50, 3)
        self.assertEqual(cards.shape, (50, 13))
        self.assertEqual(features.shape, (50, 2, 3, 3))
        for row in cards:
            self.assertEqual(len(set(row.tolist())), 13)
        total = features[..., 0] + features[..., 1]
        self.assertTrue(np.all((total >= 0) & (total <= 1)))
        self.assertTrue(np.all(features[..., 1] <= 0.5))
        self.assertTrue(np.all(features[..., 2] >= 0))

    def test_kmeans_finds_separate_clusters_and_assign_uses_nearest(self) -> None:
        rng = np.random.default_rng(1)
        centres = np.array([[0.1, 0.0, 0.1], [0.5, 0.2, 0.3], [0.9, 0.05, 0.2]], dtype=np.float32)
        points = np.concatenate([c + rng.normal(0, 0.01, (300, 3)) for c in centres]).astype(np.float32)
        found = kmeans(points, 3, seed=2)
        self.assertEqual(found.shape, (3, 3))
        np.testing.assert_allclose(found, centres, atol=0.01)  # sorted by total equity
        labels = assign(points, found)
        self.assertEqual(set(labels[:300].tolist()), {0})
        self.assertEqual(set(labels[600:].tolist()), {2})

    def test_chunks_cluster_into_a_pool_that_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as d, patch.object(pool, "CHUNK", 200):
            directory = Path(d)
            generate_chunks(400, directory)
            generate_chunks(400, directory)  # resumes: nothing new
            self.assertEqual(len(pool.chunk_paths(directory)), 2)
            built = build_pool((5, 6, 7), directory, sample=800)
            self.assertEqual(built.counts, (5, 6, 7))
            self.assertEqual(built.cards.shape, (400, 13))
            self.assertLess(int(built.buckets[:, :, 2].max()), 7)
            built.save(directory / "pool.npz")
            again = DealPool.load(directory / "pool.npz")
            np.testing.assert_array_equal(built.buckets, again.buckets)


if __name__ == "__main__":
    unittest.main()
