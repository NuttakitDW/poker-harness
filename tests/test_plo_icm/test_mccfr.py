import unittest

import numpy as np

from plo_icm.config import Config
from plo_icm.game import Action
from plo_icm.solver import InfoSet, Solver


class ToyState:
    def __init__(self, depth=0, payoff=None):
        self.depth, self.payoff = depth, payoff
        self.terminal = payoff is not None
        self.actor = None if self.terminal else depth

    def legal_actions(self):
        return (Action.CHECK, Action.POT)

    def apply(self, action):
        if self.depth == 0:
            return ToyState(payoff=1 if action == Action.CHECK else 0)
        return ToyState(payoff=0)


def config(seed=3):
    return Config.from_dict(dict(stacks=[2] * 6, payouts=[60], players_remaining=6,
        outside_stack=2, ante=.1, ante_mode="individual", iterations=0, seed=seed,
        max_nodes=1_000_000))


class MCCFRToyTest(unittest.TestCase):
    def test_external_sampling_regret_moves_toward_dominant_action(self):
        solver = Solver(config())
        solver._key = lambda state, seat, hole, board: "root"  # type: ignore[method-assign]
        solver._terminal = lambda state, holes, board: np.array([state.payoff] + [0] * 5, dtype=float)  # type: ignore[method-assign]
        holes = (("As", "Ks", "Qd", "Jd"),) * 6
        for _ in range(20):
            delta = {}
            solver._traverse(ToyState(), holes, (), 0, delta)
            solver.infosets["root"].regrets += delta["root"]
        self.assertGreater(solver.infosets["root"].strategy()[0], .99)

    def test_full_support_average_pass_unbiases_sampled_reach(self):
        class AverageToy(ToyState):
            def apply(self, action):
                if self.depth == 0 and action == Action.CHECK:
                    return AverageToy(depth=1)
                return AverageToy(payoff=0)

        solver = Solver(config(seed=9))
        solver._key = lambda state, seat, hole, board: f"n{state.depth}"  # type: ignore[method-assign]
        solver.infosets["n0"] = InfoSet(("check", "pot"), np.array([3., 1.]), np.zeros(2))
        solver.infosets["n1"] = InfoSet(("check", "pot"), np.array([1., 4.]), np.zeros(2))
        holes = (("As", "Ks", "Qd", "Jd"),) * 6
        total = np.zeros(2)
        samples = 20_000
        for _ in range(samples):
            delta = {}
            solver._average_pass(AverageToy(), holes, (), np.ones(6), 1., delta)
            if "n1" in delta:
                total += delta["n1"]
        np.testing.assert_allclose(total / samples, solver.infosets["n1"].strategy(), atol=.015)


if __name__ == "__main__":
    unittest.main()
