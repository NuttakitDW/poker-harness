import dataclasses
import json
import random
import unittest

import numpy as np

from plo_chipev.abstraction import hand_observation, information_key
from plo_chipev.config import Config
from plo_chipev.game import PreflopState
from plo_chipev.solver import InfoSet, Solver
from plo_icm.cards import deal
from plo_icm.game import Action


class HiddenToyState:
    def __init__(self, world, payoff=None):
        self.world = world
        self.payoff = payoff
        self.terminal = payoff is not None
        self.actor = None if self.terminal else 0

    def legal_actions(self):
        return (Action.FOLD, Action.CALL)

    def apply(self, action):
        chose_first = action == Action.FOLD
        return HiddenToyState(self.world, float(chose_first == (self.world == 0)))


class HiddenToySolver(Solver):
    def _key(self, state, seat, observation):
        return "same-own-information"

    def _terminal(self, state, ranks):
        return np.asarray([state.payoff, 0, 0, 0, 0, 0], dtype=float)


class AverageToyState:
    def __init__(self, depth=0, terminal=False):
        self.depth = depth
        self.terminal = terminal
        self.actor = None if terminal else depth

    def legal_actions(self):
        return (Action.FOLD, Action.CALL)

    def apply(self, action):
        if self.depth == 0 and action == Action.FOLD:
            return AverageToyState(depth=1)
        return AverageToyState(terminal=True)


class AverageToySolver(Solver):
    def _key(self, state, seat, observation):
        return f"node-{state.depth}"


class SolverTest(unittest.TestCase):
    def test_information_key_uses_only_own_hand_feature_and_public_history(self):
        state = PreflopState.new().apply(Action.CALL)
        first_holes, first_board = deal(random.Random(13))
        own = first_holes[state.actor]
        hidden = [
            card
            for seat, hole in enumerate(first_holes)
            if seat != state.actor
            for card in hole
        ] + list(first_board)
        hidden.reverse()
        second_holes = []
        cursor = 0
        for seat in range(6):
            if seat == state.actor:
                second_holes.append(own)
            else:
                second_holes.append(tuple(hidden[cursor:cursor + 4]))
                cursor += 4
        second_board = tuple(hidden[cursor:cursor + 5])
        self.assertNotEqual((first_holes, first_board), (tuple(second_holes), second_board))
        for holes, board in ((first_holes, first_board), (tuple(second_holes), second_board)):
            self.assertEqual(len({card for hole in holes for card in hole} | set(board)), 29)

        solver = Solver(Config(iterations=0))
        observation = hand_observation(own, "features")
        first = solver._key(state, state.actor, observation)
        second = solver._key(state, state.actor, observation)

        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(first),
            [state.actor, "features", json.loads(first)[2], list(state.history)],
        )
        self.assertEqual(first, second)


    def test_exact_abstraction_is_canonical_over_suit_names_and_hole_order(self):
        state = PreflopState.new()
        first = information_key(state, 0, ("As", "Ks", "Qd", "Jd"), "exact")
        second = information_key(state, 0, ("Jc", "Ah", "Kh", "Qc"), "exact")
        self.assertEqual(first, second)


    def test_zero_support_average_is_explicitly_uniform_not_current_policy(self):
        info = InfoSet.new((Action.FOLD, Action.CALL, Action.POT))
        info.regrets[:] = (0.0, 2.0, 8.0)

        np.testing.assert_allclose(info.current_strategy(), (0.0, 0.2, 0.8))
        np.testing.assert_allclose(info.average_strategy(), (1 / 3, 1 / 3, 1 / 3))


    def test_seeded_smoke_training_is_reproducible_and_chip_ev(self):
        config = Config(iterations=2, seed=19, max_nodes=100_000, max_infosets=20_000)
        first = Solver(config)
        second = Solver(config)

        first_meta = first.train()
        second_meta = second.train()

        self.assertEqual(first_meta["iterations_completed"], 2)
        self.assertEqual(second_meta["iterations_completed"], 2)
        self.assertEqual(
            first_meta["utility_units"],
            "bb chip EV (final stack minus starting stack)",
        )
        self.assertFalse(first_meta["convergence_guarantee"])
        self.assertFalse(first_meta["ordinary_plo_optimum"])
        self.assertEqual(first.deterministic_state(), second.deterministic_state())


    def test_terminal_utility_is_final_stack_minus_starting_stack(self):
        solver = Solver(Config(iterations=0))
        np.testing.assert_allclose(
            solver.terminal_utilities((103.0, 99.0, 98.0, 100.0, 100.0, 100.0)),
            (3.0, -1.0, -2.0, 0.0, 0.0, 0.0),
        )

    def test_same_traversal_and_averaging_learn_hidden_information_toy(self):
        solver = HiddenToySolver(Config(iterations=0, seed=73))
        chance = random.Random(9001)
        observations = ("private",) * 6
        for _ in range(500):
            state = HiddenToyState(world=0 if chance.random() < 0.75 else 1)
            regret_delta = {}
            solver._traverse(state, observations, (0,) * 6, 0, regret_delta)
            info = solver.infosets["same-own-information"]
            info.regrets += regret_delta["same-own-information"]
            info.visits += 1
            average_delta = {}
            solver._average_pass(state, observations, np.ones(6), 1.0, average_delta)
            info.strategy_sum += average_delta["same-own-information"]

        strategy = solver.infosets["same-own-information"].average_strategy()
        expected_payoff = 0.75 * strategy[0] + 0.25 * strategy[1]
        self.assertGreater(expected_payoff, 0.70)
        self.assertGreater(strategy[0], 0.90)

    def test_averaging_pass_corrects_own_and_sampled_reach(self):
        solver = AverageToySolver(Config(iterations=0, seed=109))
        solver.infosets["node-0"] = InfoSet(
            ("fold", "call"), np.asarray([3.0, 1.0]), np.zeros(2)
        )
        solver.infosets["node-1"] = InfoSet(
            ("fold", "call"), np.asarray([1.0, 4.0]), np.zeros(2)
        )
        total = np.zeros(2)
        samples = 10_000
        for _ in range(samples):
            delta = {}
            solver._average_pass(
                AverageToyState(), ("private",) * 6, np.ones(6), 1.0, delta
            )
            if "node-1" in delta:
                total += delta["node-1"]
        np.testing.assert_allclose(
            total / samples,
            solver.infosets["node-1"].current_strategy(),
            atol=0.02,
        )

    def test_node_budget_is_cumulative_across_training_chunks(self):
        solver = Solver(Config(iterations=1, seed=4, max_nodes=100_000))
        solver.train()
        completed = solver.completed_iterations
        solver.config = dataclasses.replace(solver.config, max_nodes=solver.nodes)

        metadata = solver.train(additional_iterations=10)

        self.assertEqual(metadata["stop_reason"], "max_nodes")
        self.assertEqual(solver.completed_iterations, completed)

    def test_train_rejects_boolean_and_nonfinite_seconds(self):
        solver = Solver(Config(iterations=0))
        for seconds in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                solver.train(additional_iterations=0, seconds=seconds)
