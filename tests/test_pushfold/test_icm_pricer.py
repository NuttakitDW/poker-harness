"""The ICM Pricer: every ending priced by the ICM value of each way the showdown can go."""

import itertools
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import auditor, cashier, floor, hands, icm, icm_pricer, oddsmaker, pricer  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

SPOTS = (
    Spot((10, 10)),
    Spot((4, 25)),
    Spot((10, 10, 10)),
    Spot((3, 10, 20)),                              # side pot
    Spot((5, 12, 8, 20), ante=0.125),
    Spot((1.5,) * 5, ante=1.0, ante_mode="bb"),     # BB all-in by posting
    Spot((6, 9, 14, 4, 11, 7), ante=0.1),
)


def random_strategy(tree: floor.Tree, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    jam = rng.uniform(0, 1, (len(tree.nodes), 169))
    return np.stack([1 - jam, jam], axis=2)


class WinnerTakeAllTest(unittest.TestCase):
    def test_same_values_as_the_chip_ev_pricer(self):
        # One prize: ICM value is the stack itself, so every value must match chip EV.
        for i, spot in enumerate(SPOTS):
            tree = floor.build(spot)
            cols = pricer.columns(random_strategy(tree, i))
            chip = pricer.plan(tree)
            ours = icm_pricer.plan(tree, icm.Payouts((1,)))
            for a, b in zip(chip, ours):
                with self.subTest(spot=spot, seat=a.seat):
                    want_cfv, want_fixed = pricer.values(a, cols)
                    got_cfv, got_fixed = b.price(cols)
                    np.testing.assert_allclose(got_cfv, want_cfv, atol=2e-4)
                    np.testing.assert_allclose(got_fixed, want_fixed, atol=2e-4)


def reference(tree: floor.Tree, sigma: np.ndarray, payouts: icm.Payouts, seat: int):
    """Straight from the definition, one terminal at a time, 3+ players (independent deals).

    Axes are the classes of the players still in; everyone else only adds a reach factor.
    Payoffs come straight from the Cashier and ICM, chances from e2 and orders().
    """
    spot = tree.spot
    nodes = [n.index for n in tree.nodes_of(seat)]
    out, fixed = np.zeros((len(nodes), 169, 2)), np.zeros(169)
    o, e2, prior = oddsmaker.orders().astype(float), oddsmaker.two_way(), hands.PRIOR
    before = icm.value(np.array([spot.stacks]), spot.stacks, payouts)[0]
    for z in tree.terminals:
        act = {j: sigma[z.nodes[j]][:, z.actions[j]] if z.nodes[j] >= 0 else np.ones(169)
               for j in range(spot.n)}
        settlement = cashier.settle(spot, z.jammers)
        alive = z.alive
        total = 0.0
        for order in itertools.permutations(alive):
            net = settlement.net_for({s: place + 1 for place, s in enumerate(order)})
            worth = icm.value(np.array([spot.stacks]) + net, spot.stacks, payouts)[0] - before
            if len(alive) == 1:
                chance = np.ones(())
            elif len(alive) == 2:
                chance = e2 if order[0] == alive[0] else e2.T
            else:
                chance = o.transpose([order.index(s) for s in alive])
            total = total + worth[seat] * chance
        total = total * np.ones((169,) * len(alive))
        for axis, j in reversed(list(enumerate(alive))):
            if j != seat:
                total = np.tensordot(total, prior * act[j], axes=([axis], [0]))
        reach = np.prod([prior @ act[j] for j in range(spot.n) if j != seat and j not in alive])
        value = total * reach * np.ones(169)
        if z.nodes[seat] < 0:
            fixed += value
        else:
            out[nodes.index(z.nodes[seat]), :, z.actions[seat]] += value
    return out, fixed


class ReferenceTest(unittest.TestCase):
    def test_bubble_values_match_the_definition(self):
        payouts = icm.Payouts((50, 30, 20))
        for i, spot in enumerate((Spot((10, 10, 10)), Spot((3, 10, 20)),
                                  Spot((5, 12, 8, 20), ante=0.125), Spot((9, 4, 14, 6)),
                                  Spot((6, 1.5, 9, 1.5), ante=1.0, ante_mode="bb"))):  # BB all-in by posting
            tree = floor.build(spot)
            sigma = random_strategy(tree, 20 + i)
            plans = icm_pricer.plan(tree, payouts)
            for p in plans:
                with self.subTest(spot=spot, seat=p.seat):
                    want_cfv, want_fixed = reference(tree, sigma, payouts, p.seat)
                    got_cfv, got_fixed = p.price(pricer.columns(sigma))
                    np.testing.assert_allclose(got_cfv, want_cfv, atol=5e-5)
                    np.testing.assert_allclose(got_fixed, want_fixed, atol=5e-5)


class ConservationTest(unittest.TestCase):
    def test_icm_evs_add_up_to_zero(self):
        # Prize money only moves between players: what one seat gains, the others lose.
        payouts = icm.Payouts((50, 30, 20))
        for i, spot in enumerate(SPOTS[2:]):
            tree = floor.build(spot)
            report = auditor.audit(tree, random_strategy(tree, 10 + i), payouts=payouts)
            with self.subTest(spot=spot):
                self.assertAlmostEqual(float(report.ev.sum()), 0.0, places=4)

    def test_heads_up_evs_add_up_to_zero(self):
        tree = floor.build(Spot((7, 13)))
        report = auditor.audit(tree, random_strategy(tree, 3), payouts=icm.Payouts((65, 35)))
        self.assertAlmostEqual(float(report.ev.sum()), 0.0, places=9)


class PlanTest(unittest.TestCase):
    def test_without_payouts_the_chip_ev_pricer_is_used(self):
        tree = floor.build(Spot((10, 10, 10)))
        self.assertIsInstance(icm_pricer.plans_for(tree, None)[0], pricer.SeatPlan)
        self.assertIsInstance(icm_pricer.plans_for(tree, icm.Payouts((1,)))[0], icm_pricer.SeatPlan)

    def test_more_places_paid_than_players_fails_clearly(self):
        with self.assertRaisesRegex(icm.PayoutError, "places"):
            icm_pricer.plan(floor.build(Spot((10, 10))), icm.Payouts((50, 30, 20)))


if __name__ == "__main__":
    unittest.main()
