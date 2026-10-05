from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from o8_fl import match
from o8_fl.buckets import Abstraction
from o8_fl.pool import DealPool
from o8_fl.ranges import COMBOS
from o8_fl.trainer import Trainer
from o8_fl.tree import DECISION, PublicTree


def tiny_pool(seed: int, dims: int) -> DealPool:
    rng = np.random.default_rng(seed)
    cards = np.array([rng.permutation(52)[:13] for _ in range(200)], dtype=np.uint8)
    buckets = rng.integers(0, 3, size=(200, 2, 3)).astype(np.uint16)
    return DealPool(cards, buckets, tuple(rng.random((3, dims)).astype(np.float32) for _ in range(3)))


class MatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.abstraction = Abstraction.build(samples=20_000)
        cls.tree = PublicTree.build()

    def _solution(self, directory: Path, name: str, seed: int, dims: int, iterations: int) -> tuple[Path, Path]:
        pool = tiny_pool(seed, dims)
        trainer = Trainer(self.tree, self.abstraction, pool)
        trainer.run(iterations, threads=1, seed=seed)
        run = directory / name
        trainer.save(run / "checkpoint.npz")
        pool.save(directory / f"{name}.npz")
        return run, directory / f"{name}.npz"

    def test_policy_rows_are_distributions_over_legal_actions(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            run, pool = self._solution(Path(d), "a", 1, 5, 300)
            solution = match.load_solution(run, pool, self.tree, self.abstraction)
        rows = solution["policy"].reshape(-1, 3)
        np.testing.assert_allclose(rows.sum(axis=1), 1.0, atol=1e-5)
        node = int(np.flatnonzero(self.tree.kind == DECISION)[0])
        illegal = self.tree.children[node] < 0
        start = solution["offsets"][node] // 3
        self.assertTrue(np.all(rows[start:start + 3][:, illegal] == 0))

    def test_a_solution_breaks_even_against_itself_and_results_are_antisymmetric(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            a = match.load_solution(*self._solution(directory, "a", 1, 5, 2000), self.tree, self.abstraction)
            b = match.load_solution(*self._solution(directory, "b", 2, 3, 50), self.tree, self.abstraction)
            strong = directory / "range.npz"
            np.savez(strong, weights=np.ones(len(COMBOS), dtype=np.float32))
            cards, features = match.held_out_deals(300, directory / "deals.npz", strong, chunk=100)
            self.assertEqual(features.shape, (300, 2, 3, 5))
            again = match.held_out_deals(200, directory / "deals.npz", strong)  # served from the cache
            np.testing.assert_array_equal(again[0], cards[:200])
            same, _, _ = match.play(cards, features, a, a, self.tree, self.abstraction)
            np.testing.assert_allclose(same, 0.0, atol=1e-9)
            ab, post_a, post_b = match.play(cards, features, a, b, self.tree, self.abstraction)
            ba, _, _ = match.play(cards, features, b, a, self.tree, self.abstraction)
            np.testing.assert_allclose(ab, -ba, atol=1e-9)
            self.assertTrue(np.all(np.abs(ab) <= 25))  # at most every bet capped on all four streets
            self.assertLess(int(post_b.max()), 3)

    def test_main_writes_a_report(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            run_a, pool_a = self._solution(directory, "a", 1, 5, 500)
            run_b, pool_b = self._solution(directory, "b", 2, 3, 500)
            strong = directory / "range.npz"
            np.savez(strong, weights=np.ones(len(COMBOS), dtype=np.float32))
            with patch.object(match.Abstraction, "cached", return_value=self.abstraction):
                match.main(["--a", str(run_a), str(pool_a), "--b", str(run_b), str(pool_b), "--deals", "100",
                            "--out", str(directory / "m.json"), "--cache", str(directory / "deals.npz"),
                            "--range", str(strong)])
            report = json.loads((directory / "m.json").read_text())
            self.assertEqual(report["deals"], 100)
            self.assertIn("strong", report["spread"]["a"]["flop"])


if __name__ == "__main__":
    unittest.main()
