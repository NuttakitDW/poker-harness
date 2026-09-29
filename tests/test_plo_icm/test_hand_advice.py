import itertools
import random
import time
import unittest
from unittest import mock

import numpy as np

from plo_icm.abstraction import AbstractSolver, abstract_key, resolve_hand, suit_orbit
from plo_icm.config import Config
from plo_icm.game import Action, PLOState
import plo_icm.hand_advice as hand_advice
from plo_icm.hand_advice import _fold_to_seat, _rollout, solve_hand, weighted_action_values
from plo_icm.solver import InfoSet


class ResolutionTest(unittest.TestCase):
    def test_resolves_common_shorthand_without_hardcoded_hand_actions(self):
        self.assertEqual(set(resolve_hand("AAKK", shape="double-suited")), {"As", "Ah", "Ks", "Kh"})
        self.assertEqual(set(resolve_hand("AK74", suited_group=("A", "K", "7"))),
                         {"As", "Ks", "7s", "4d"})

    def test_ambiguous_double_suited_pairing_requires_exact_suits(self):
        with self.assertRaisesRegex(ValueError, "exact suits"):
            resolve_hand("AKQJ", shape="double-suited")

    def test_orbit_probability_and_importance_weights_are_unbiased(self):
        hand = resolve_hand("AAKK", shape="double-suited")
        orbit = suit_orbit(hand)
        p = len(orbit) / 270725
        lam = .8
        target_weight = 1 / ((1 - lam) + lam / p)
        other_weight = 1 / (1 - lam)
        q_target = (1 - lam) * p + lam
        self.assertAlmostEqual(q_target * target_weight + (1 - q_target) * other_weight, 1)


class InformationTest(unittest.TestCase):
    def test_key_keeps_history_and_hides_exact_cards_and_target_from_opponents(self):
        state = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        holes = (("As", "Ks", "7s", "4d"),) + tuple(
            tuple(cards) for cards in itertools.islice(itertools.combinations(
                [r + s for r in "23456789TJQ" for s in "cdh"], 4), 5))
        board = ("2s", "3d", "4h", "5c", "6s")
        own = abstract_key(state, 1, holes[1], board, focal_seat=0)
        changed = abstract_key(state, 1, holes[1], board, focal_seat=5)
        self.assertEqual(own, changed)
        self.assertNotIn("As", own)
        after = state.apply(Action.FOLD)
        self.assertNotEqual(own, abstract_key(after, 1, holes[1], board, focal_seat=0))

    def test_only_focal_players_own_target_class_is_flagged(self):
        state = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        hand = ("As", "Ah", "Ks", "Kh")
        target = abstract_key(state, 3, hand, (), 3, True)
        ordinary = abstract_key(state, 3, hand, (), 3, False)
        opponent_a = abstract_key(state, 2, hand, (), 3, True)
        opponent_b = abstract_key(state, 2, hand, (), 3, False)
        self.assertNotEqual(target, ordinary)
        self.assertEqual(opponent_a, opponent_b)


class EstimatorToyTest(unittest.TestCase):
    def test_weighted_values_rank_known_actions_and_price_zero_reach(self):
        samples = [(2., {"fold": 1., "call": 3.}), (1., {"fold": 2., "call": 4.})]
        result = weighted_action_values(samples)
        self.assertEqual(result.best, "call")
        self.assertAlmostEqual(result.ev["fold"], 4 / 3)
        self.assertAlmostEqual(result.pairwise_se["call|fold"], 0)
        with self.assertRaisesRegex(ValueError, "reach"):
            weighted_action_values([(0., {"fold": 1., "call": 2.})])
        one = weighted_action_values([(1., {"fold": 1., "call": 2.})])
        self.assertIsNone(one.se_vs_best["fold"])

    def test_abstract_training_is_reproducible_and_bounded(self):
        cfg = Config.from_dict(dict(stacks=[3] * 6, payouts=[60], players_remaining=6,
            outside_stack=3, ante=.1, ante_mode="individual", iterations=2, seed=17,
            max_nodes=2000))
        hand = resolve_hand("AAKK", shape="double-suited")
        a, b = AbstractSolver(cfg, focal_seat=3, focal_hand=hand), AbstractSolver(cfg, focal_seat=3, focal_hand=hand)
        a.train(); b.train()
        self.assertEqual(a.to_dict()["infosets"], b.to_dict()["infosets"])
        self.assertFalse(a.metadata()["convergence_guarantee"])

    def test_training_applies_chance_weight_to_regret_and_average_once(self):
        cfg = Config.from_dict(dict(stacks=[3] * 6, payouts=[60], players_remaining=6,
            outside_stack=3, ante=.1, ante_mode="individual", iterations=1, seed=17,
            max_nodes=2000))

        class WeightedSolver(AbstractSolver):
            def _mixture_deal(self):
                return (((),) * 6, (), 3.0)

            def _traverse(self, state, holes, board, target, deltas):
                legal = state.legal_actions()
                self.infosets.setdefault("toy", InfoSet.new(legal))
                deltas["toy"] = np.ones(len(legal))
                return np.zeros(6)

            def _average_pass(self, state, holes, board, own, sampled, deltas):
                deltas["toy"] = np.full(len(state.legal_actions()), 2.0)

        solver = WeightedSolver(cfg, focal_seat=3,
                                focal_hand=("As", "Ah", "Ks", "Kh"))
        solver.train()
        self.assertTrue(np.all(solver.infosets["toy"].regrets == 18))
        self.assertTrue(np.all(solver.infosets["toy"].strategy_sum == 6))

    def test_fold_conditioning_uses_actual_prefix_actors(self):
        state = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        policies = iter((.5, .4, .3))

        def policy(_solver, current, _holes, _board):
            legal = current.legal_actions()
            fold = next(policies)
            probabilities = np.zeros(len(legal))
            probabilities[legal.index(Action.FOLD)] = fold
            probabilities[legal.index(Action.CALL)] = 1 - fold
            return legal, probabilities, False

        with mock.patch.object(hand_advice, "_policy", side_effect=policy):
            reached, weight, missing, decisions = _fold_to_seat(
                object(), state, 3, ((),) * 6, ())
        self.assertEqual(reached.actor, 3)
        self.assertAlmostEqual(weight, .5 * .4 * .3)
        self.assertEqual((missing, decisions), (0, 3))

    def test_rollout_after_hero_fold_continues_until_a_real_terminal(self):
        state = PLOState.new((10,) * 6, ante=.1, ante_mode="individual")
        for _ in range(3):
            state = state.apply(Action.FOLD)
        state = state.apply(Action.FOLD)  # BTN folds; SB and BB still have decisions.
        calls = []

        class FakeSolver:
            def _sample_index(self, probabilities):
                return int(np.argmax(probabilities))

            def terminal_utilities(self, final):
                return final

        def policy(_solver, current, _holes, _board):
            calls.append(current.actor)
            legal = current.legal_actions()
            probabilities = np.zeros(len(legal))
            choice = Action.FOLD if Action.FOLD in legal else legal[0]
            probabilities[legal.index(choice)] = 1
            return legal, probabilities, False

        holes = (("As", "Ah", "Ks", "Kh"), ("2s", "2h", "3s", "3h"),
                 ("4s", "4h", "5s", "5h"), ("6s", "6h", "7s", "7h"),
                 ("8s", "8h", "9s", "9h"), ("Ts", "Th", "Js", "Jh"))
        board = ("Qd", "Kd", "Ad", "2d", "3d")
        with mock.patch.object(hand_advice, "_policy", side_effect=policy):
            utility, _, _ = _rollout(FakeSolver(), state, holes, board,
                                     time.perf_counter() + 1)
        self.assertTrue(calls)
        self.assertAlmostEqual(float(np.sum(utility)), 60)

    def test_evaluation_deadline_and_invalid_unbounded_budget(self):
        cfg = Config.from_dict(dict(stacks=[3] * 6, payouts=[60], players_remaining=6,
            outside_stack=3, ante=.1, ante_mode="individual", iterations=0, seed=17,
            max_nodes=2000))
        hand = ("As", "Ah", "Ks", "Kh")
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            solve_hand(cfg, 3, hand, train_seconds=.01, eval_seconds=float("inf"))
        state = PLOState.new((3,) * 6, ante=.1, ante_mode="individual")
        with self.assertRaises(TimeoutError):
            _rollout(object(), state, ((),) * 6, (), time.perf_counter() - 1)

    def test_solve_hand_runs_paired_actions_and_reports_state_amount(self):
        cfg = Config.from_dict(dict(stacks=[10] * 6, payouts=[60], players_remaining=6,
            outside_stack=10, ante=.1, ante_mode="individual", iterations=0, seed=17,
            max_nodes=2000))
        deck = [r + s for r in "23456789TJQKA" for s in "cdhs"]
        holes = tuple(tuple(deck[i:i + 4]) for i in range(0, 24, 4))
        board = tuple(deck[24:29])

        class FakeAbstractSolver:
            VERSION = "toy"

            def __init__(self, config, **_kwargs):
                self.config = config
                self.rng = random.Random(config.seed)
                self.infosets = {}

            def train(self):
                return {}

            def _target_deal(self):
                return holes, board

            def _key(self, state, seat, hole, shown):
                return str((seat, state.history, hole, shown))

            def _sample_index(self, probabilities):
                return 0

            def metadata(self):
                return {"claim": "toy"}

        def rollout(_solver, state, _holes, _board, _deadline):
            action = state.history[-1].split(":")[2]
            score = {"fold": 0., "call": 1., "raise_2bb": 2., "pot": 3.}[action]
            utility = np.zeros(6); utility[3] = score
            return utility, 0, 1

        with mock.patch.object(hand_advice, "AbstractSolver", FakeAbstractSolver), \
             mock.patch.object(hand_advice, "_rollout", side_effect=rollout):
            result = solve_hand(cfg, 3, ("As", "Ah", "Ks", "Kh"),
                                train_seconds=.01, eval_seconds=1, min_samples=1,
                                eval_attempts=5, eval_seed=99)
        self.assertEqual((result.action, result.amount), ("raise_2bb", 2))
        self.assertEqual((result.samples, result.evaluation_attempts, result.evaluation_complete),
                         (5, 5, True))

        calls = 0
        def interrupted(*args):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise TimeoutError
            return rollout(*args)

        with mock.patch.object(hand_advice, "AbstractSolver", FakeAbstractSolver), \
             mock.patch.object(hand_advice, "_rollout", side_effect=interrupted):
            partial = solve_hand(cfg, 3, ("As", "Ah", "Ks", "Kh"),
                                 train_seconds=.01, eval_seconds=1, min_samples=1,
                                 eval_attempts=2, eval_seed=99)
        self.assertEqual((partial.samples, partial.evaluation_attempts, partial.evaluation_complete),
                         (1, 1, False))


if __name__ == "__main__":
    unittest.main()
