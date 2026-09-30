from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from plo_chipev.checkpoint import save_checkpoint as save_legacy_checkpoint
from plo_chipev.config import Config
from plo_chipev.solver import Solver
from plo_chipev_fast.checkpoint import load_checkpoint, save_checkpoint
from plo_chipev_fast.hands import HandLookup
from plo_chipev_fast.model import DenseModel
from plo_chipev_fast.trainer import (
    GOLDEN,
    MASK64,
    FastTrainer,
    _iteration_kernel,
    _toy_iteration,
)
from plo_chipev_fast.tree import PublicTree, settle_terminal


def _next_unit(state: list[int]) -> float:
    state[0] = (state[0] + GOLDEN) & MASK64
    value = state[0]
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
    value ^= value >> 31
    return float(value >> 11) * (1.0 / 9007199254740992.0)


def _python_iteration(
    model: DenseModel,
    buckets: np.ndarray,
    ranks: np.ndarray,
    sampling_seed: int,
) -> tuple[int, int, set[int], set[int]]:
    """Independent recursive oracle for one frozen-policy production iteration."""
    tree = model.tree
    frozen = model.regrets.copy()
    state = [sampling_seed]
    regret_updates: list[tuple[int, int, np.ndarray]] = []
    average_updates: list[tuple[int, int, np.ndarray]] = []
    touched_counts: set[int] = set()
    touched_actors: set[int] = set()
    nodes = 0

    def probabilities(node: int) -> np.ndarray:
        decision = int(tree.decision_index[node])
        bucket = int(buckets[int(tree.actor[node])])
        count = int(tree.action_count[node])
        positive = np.maximum(frozen[decision, bucket, :count], 0.0)
        return (
            positive / positive.sum()
            if positive.sum() > 0
            else np.full(count, 1.0 / count)
        )

    def sample(probabilities: np.ndarray) -> int:
        point = _next_unit(state)
        cumulative = 0.0
        for index, probability in enumerate(probabilities):
            cumulative += float(probability)
            if point <= cumulative + 1e-15:
                return index
        return len(probabilities) - 1

    def traverse(node: int, target: int) -> float:
        nonlocal nodes
        nodes += 1
        seat = int(tree.actor[node])
        if seat < 0:
            return float(settle_terminal(tree, node, ranks)[target] - 100.0)
        policy = probabilities(node)
        if seat != target:
            return traverse(int(tree.children[node, sample(policy)]), target)
        values = np.asarray(
            [traverse(int(tree.children[node, action]), target) for action in range(len(policy))]
        )
        expected = float(policy @ values)
        decision = int(tree.decision_index[node])
        bucket = int(buckets[seat])
        regret_updates.append((decision, bucket, values - expected))
        touched_counts.add(len(policy))
        touched_actors.add(seat)
        return expected

    for target in range(6):
        traverse(0, target)

    own_reach = np.ones(6)
    sampled_reach = 1.0
    node = 0
    while tree.actor[node] >= 0:
        nodes += 1
        seat = int(tree.actor[node])
        policy = probabilities(node)
        decision = int(tree.decision_index[node])
        bucket = int(buckets[seat])
        average_updates.append((decision, bucket, own_reach[seat] / sampled_reach * policy))
        sample_policy = 0.95 * policy + 0.05 / len(policy)
        choice = sample(sample_policy)
        own_reach[seat] *= policy[choice]
        sampled_reach *= sample_policy[choice]
        node = int(tree.children[node, choice])
    nodes += 1

    for decision, bucket, delta in regret_updates:
        model.regrets[decision, bucket, : len(delta)] += delta
        model.visits[decision, bucket] += 1
    for decision, bucket, delta in average_updates:
        model.strategy_sum[decision, bucket, : len(delta)] += delta
    return state[0], nodes, touched_counts, touched_actors


class TrainerTest(unittest.TestCase):
    def test_toy_regret_and_average_updates_use_frozen_policy(self) -> None:
        regrets = np.zeros((1, 1, 3), dtype=np.float64)
        average = np.zeros_like(regrets)
        visits = np.zeros((1, 1), dtype=np.int64)
        _toy_iteration(regrets, average, visits, np.array((0.0, 2.0, -1.0)))
        np.testing.assert_allclose(regrets[0, 0], (-1 / 3, 5 / 3, -4 / 3))
        np.testing.assert_allclose(average[0, 0], (1 / 3, 1 / 3, 1 / 3))
        self.assertEqual(visits[0, 0], 1)

    def test_hidden_rank_changes_do_not_change_policy_access(self) -> None:
        tree = PublicTree.build()
        hands = HandLookup.build()
        model = DenseModel.empty(tree, hands)
        decision = int(tree.decision_index[0])
        bucket = hands.bucket_for_cards((0, 1, 2, 3))
        model.regrets[decision, bucket] = (0.0, 2.0, 1.0)
        before = model.current_policy(0, bucket).copy()
        # Opponent cards/ranks are intentionally absent from this API.
        after = model.current_policy(0, bucket).copy()
        np.testing.assert_array_equal(before, after)

    def test_split_training_exactly_matches_uninterrupted_resume_state(self) -> None:
        tree = PublicTree.build()
        hands = HandLookup.build()
        whole = FastTrainer(DenseModel.empty(tree, hands), chance_seed=91, sampling_seed=92)
        split = FastTrainer(DenseModel.empty(tree, hands), chance_seed=91, sampling_seed=92)
        whole.train(iterations=3)
        with tempfile.TemporaryDirectory() as directory:
            split.train(iterations=1)
            save_checkpoint(split, Path(directory), overwrite=True)
            restored, _ = load_checkpoint(Path(directory), tree, hands)
            restored.train(iterations=2)
            self.assertEqual(whole.deterministic_state(), restored.deterministic_state())
            np.testing.assert_array_equal(whole.model.regrets, restored.model.regrets)
            np.testing.assert_array_equal(whole.model.strategy_sum, restored.model.strategy_sum)
            np.testing.assert_array_equal(whole.model.visits, restored.model.visits)

    def test_production_numba_iteration_matches_independent_python_same_tape(self) -> None:
        tree = PublicTree.build()
        hands = HandLookup.build()
        compiled = DenseModel.empty(tree, hands)
        chance = FastTrainer(compiled, chance_seed=771, sampling_seed=991)
        buckets, ranks, _ = chance._prepare_chance()
        for node in np.flatnonzero(tree.actor >= 0):
            decision = int(tree.decision_index[node])
            bucket = int(buckets[int(tree.actor[node])])
            count = int(tree.action_count[node])
            compiled.regrets[decision, bucket, :count] = (
                np.asarray((1.0 + decision % 5, 2.0 + decision % 3, 0.5))[:count]
            )
            compiled.strategy_sum[decision, bucket, :count] = np.asarray((3.0, 1.0, 2.0))[
                :count
            ]
        expected = DenseModel(
            tree,
            hands,
            compiled.regrets.copy(),
            compiled.strategy_sum.copy(),
            compiled.visits.copy(),
        )
        expected_state, expected_nodes, action_counts, actors = _python_iteration(
            expected, buckets, ranks, 991
        )
        state = np.asarray((991,), dtype=np.uint64)
        actual_nodes = _iteration_kernel(
            buckets,
            ranks,
            tree.actor,
            tree.decision_index,
            tree.children,
            tree.action_count,
            tree.behind,
            tree.sidepot_count,
            tree.sidepot_amount,
            tree.sidepot_eligible_mask,
            compiled.regrets,
            compiled.strategy_sum,
            compiled.visits,
            state,
        )
        self.assertEqual(int(state[0]), expected_state)
        self.assertEqual(actual_nodes, expected_nodes)
        self.assertEqual(action_counts, {2, 3})
        self.assertEqual(actors, set(range(6)))
        np.testing.assert_array_equal(compiled.regrets, expected.regrets)
        np.testing.assert_array_equal(compiled.strategy_sum, expected.strategy_sum)
        np.testing.assert_array_equal(compiled.visits, expected.visits)

    def test_iterations_this_call_is_delta_after_imported_counters(self) -> None:
        tree = PublicTree.build()
        hands = HandLookup.build()
        trainer = FastTrainer(DenseModel.empty(tree, hands), chance_seed=1, sampling_seed=2)
        trainer.imported_iterations = trainer.completed_iterations = 10
        trainer.imported_traversals = trainer.completed_traversals = 60
        first = trainer.train(iterations=2)
        second = trainer.train(iterations=3)
        self.assertEqual(first["iterations_this_call"], 2)
        self.assertEqual(second["iterations_this_call"], 3)

    def test_cross_process_legacy_import_resume_and_reload_train(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_path = root / "legacy.json"
            output = root / "fast"
            save_legacy_checkpoint(Solver(Config(iterations=0)), legacy_path)
            commands = (
                [
                    sys.executable,
                    "-m",
                    "plo_chipev_fast",
                    "train",
                    "--output",
                    str(output),
                    "--legacy-checkpoint",
                    str(legacy_path),
                    "--iterations",
                    "1",
                ],
                [
                    sys.executable,
                    "-m",
                    "plo_chipev_fast",
                    "train",
                    "--output",
                    str(output),
                    "--resume",
                    "--iterations",
                    "1",
                ],
            )
            for command in commands:
                completed = subprocess.run(
                    command,
                    cwd=project,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
                self.assertTrue(completed.stdout.strip())
            loaded, _ = load_checkpoint(output, PublicTree.build(), HandLookup.build())
            self.assertEqual(loaded.completed_iterations, 2)
