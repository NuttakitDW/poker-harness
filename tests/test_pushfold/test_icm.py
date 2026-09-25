"""ICM: the Malmuth-Harville model that turns chip stacks into shares of the prize pool."""

import itertools
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import icm  # noqa: E402


def brute_force(stacks: list[float], prizes: list[float]) -> np.ndarray:
    """Every finish order, each with its Harville chance: slow but obviously right."""
    total, out = sum(stacks), np.zeros(len(stacks))
    for order in itertools.permutations(range(len(stacks))):
        chance, left = 1.0, total
        for seat in order:
            chance *= stacks[seat] / left
            left -= stacks[seat]
        for place, seat in enumerate(order[:len(prizes)]):
            out[seat] += chance * prizes[place]
    return out


class HarvilleTest(unittest.TestCase):
    def test_matches_every_finish_order(self):
        rng = np.random.default_rng(1)
        for n, paid in ((3, 3), (5, 3), (6, 6), (4, 1)):
            stacks = rng.uniform(1, 30, n)
            prizes = np.sort(rng.uniform(0, 1, paid))[::-1]
            with self.subTest(n=n, paid=paid):
                got = icm.harville(stacks[None, :], prizes)[0]
                np.testing.assert_allclose(got, brute_force(list(stacks), list(prizes)), atol=1e-12)

    def test_many_tables_at_once(self):
        rng = np.random.default_rng(2)
        stacks = rng.uniform(1, 20, (7, 4))
        prizes = np.array([0.5, 0.3, 0.2])
        got = icm.harville(stacks, prizes)
        for row, want in zip(got, stacks):
            np.testing.assert_allclose(row, brute_force(list(want), list(prizes)), atol=1e-12)

    def test_winner_take_all_is_chip_share(self):
        stacks = np.array([[10.0, 25.0, 5.0]])
        np.testing.assert_allclose(icm.harville(stacks, np.array([40.0]))[0], stacks[0], atol=1e-12)

    def test_a_player_with_no_chips_wins_nothing(self):
        got = icm.harville(np.array([[10.0, 0.0, 10.0]]), np.array([0.5, 0.3, 0.2]))[0]
        np.testing.assert_allclose(got, [0.4, 0.0, 0.4], atol=1e-12)


class CrowdTest(unittest.TestCase):
    """Players at other tables who all share one stack: counted, not tracked one by one."""

    def test_matches_listing_every_player(self):
        rng = np.random.default_rng(6)
        stacks = rng.uniform(1, 20, (5, 3))
        prizes = np.array([40.0, 25.0, 15.0, 10.0, 6.0, 4.0])
        got = icm.crowd_harville(stacks, prizes, crowd=4, each=7.5)
        listed = icm.harville(np.hstack([stacks, np.full((5, 4), 7.5)]), prizes)[:, :3]
        np.testing.assert_allclose(got, listed, atol=1e-12)

    def test_more_places_than_the_table_reaches(self):
        stacks = np.array([[4.0, 9.0]])
        prizes = np.linspace(10, 1, 8)
        got = icm.crowd_harville(stacks, prizes, crowd=7, each=5.0)
        listed = icm.harville(np.hstack([stacks, np.full((1, 7), 5.0)]), prizes)[:, :2]
        np.testing.assert_allclose(got, listed, atol=1e-12)

    def test_value_with_a_crowd_matches_listing_it_as_field(self):
        start = (10.0, 20.0, 5.0)
        final = np.array([start, (0.0, 30.0, 5.0), (15.0, 0.0, 20.0)])
        prizes = (30, 20, 15, 12, 10, 8, 5)
        crowd = icm.value(final, start, icm.Payouts(prizes, crowd=6, crowd_stack=12.0))
        listed = icm.value(final, start, icm.Payouts(prizes, field=(12.0,) * 6))
        np.testing.assert_allclose(crowd, listed, atol=1e-9)

    def test_hundreds_of_players_are_quick(self):
        import time  # noqa: PLC0415
        began = time.perf_counter()
        stacks = np.random.default_rng(1).uniform(1, 20, (600, 9))
        icm.value(stacks, tuple(stacks[0]), icm.Payouts(tuple(range(150, 0, -1)), crowd=491,
                                                        crowd_stack=10.0))
        self.assertLess(time.perf_counter() - began, 10.0)

    def test_rejects_a_crowd_without_a_stack(self):
        for crowd, each in ((-1, 10.0), (5, 0.0), (5, float("inf"))):
            with self.subTest(crowd=crowd, each=each), self.assertRaises(icm.PayoutError):
                icm.Payouts((1,), crowd=crowd, crowd_stack=each)

    def test_the_crowd_counts_as_players_for_places_paid(self):
        icm.Payouts((5, 4, 3, 2, 1), crowd=3, crowd_stack=10.0).check(table=2)
        with self.assertRaisesRegex(icm.PayoutError, "places"):
            icm.Payouts((5, 4, 3, 2, 1, 1), crowd=3, crowd_stack=10.0).check(table=2)


class PayoutsTest(unittest.TestCase):
    def test_prizes_are_scaled_to_the_chips_in_play(self):
        p = icm.Payouts((50, 30, 20))
        np.testing.assert_allclose(p.scaled(40.0), [20.0, 12.0, 8.0])

    def test_rejects_bad_prizes(self):
        for prizes in ((), (0, 0), (50, -1), (float("nan"),)):
            with self.subTest(prizes=prizes), self.assertRaises(icm.PayoutError):
                icm.Payouts(prizes)

    def test_rejects_bad_field_stacks(self):
        with self.assertRaises(icm.PayoutError):
            icm.Payouts((1,), field=(10, 0))

    def test_more_places_paid_than_players_fails_clearly(self):
        with self.assertRaisesRegex(icm.PayoutError, "places"):
            icm.Payouts((5, 3, 2, 1)).check(table=3)

    def test_too_many_places_among_many_players_fails_clearly(self):
        with self.assertRaisesRegex(icm.PayoutError, "places"):
            icm.Payouts(tuple(range(15, 0, -1)), field=(10,) * 11).check(table=9)

    def test_too_many_players_fails_clearly(self):
        with self.assertRaisesRegex(icm.PayoutError, "players"):
            icm.Payouts((5, 3, 2), field=(10,) * 40).check(table=9)


class ValueTest(unittest.TestCase):
    def test_values_add_up_to_the_chips_in_play(self):
        start = (10.0, 20.0, 30.0)
        got = icm.value(np.array([start, (0.0, 30.0, 30.0)]), start, icm.Payouts((50, 30, 20)))
        np.testing.assert_allclose(got.sum(axis=1), [60.0, 60.0], atol=1e-9)

    def test_field_players_count_in_the_model(self):
        # Two tables of two: the table's seats are worth what a four-player ICM says.
        start = (10.0, 20.0)
        got = icm.value(np.array([start]), start, icm.Payouts((50, 30, 20), field=(30.0, 40.0)))[0]
        want = brute_force([10, 20, 30, 40], [50, 30, 20])  # 100 chips, 100 in prizes
        np.testing.assert_allclose(got, want[:2], atol=1e-9)

    def test_winner_take_all_value_is_the_stack(self):
        start = (10.0, 20.0, 30.0)
        final = np.array([[0.0, 30.0, 30.0], [20.0, 10.0, 30.0]])
        np.testing.assert_allclose(icm.value(final, start, icm.Payouts((1,))), final, atol=1e-9)

    def test_bust_order_goes_by_stack_at_the_start_of_the_hand(self):
        # Two players bust in one hand: the bigger stack takes the higher place.
        p = icm.Payouts((50, 30, 20))
        got = icm.value(np.array([[0.0, 0.0, 60.0]]), (10.0, 20.0, 30.0), p)[0]
        np.testing.assert_allclose(got, np.array([20, 30, 50]) * 60 / 100)

    def test_equal_stacks_busting_together_split_their_places(self):
        p = icm.Payouts((50, 30, 20))
        got = icm.value(np.array([[0.0, 0.0, 60.0]]), (20.0, 20.0, 20.0), p)[0]
        np.testing.assert_allclose(got, np.array([25, 25, 50]) * 60 / 100)

    def test_a_fair_heads_up_bet_costs_the_players_and_pays_the_rest(self):
        # Gilbert (2009), theorems 1 and 2.
        p = icm.Payouts((50, 30, 20))
        start = (10.0, 20.0, 30.0)
        now = icm.value(np.array([start]), start, p)[0]
        after = icm.value(np.array([(20.0, 10.0, 30.0), (0.0, 30.0, 30.0)]), start, p).mean(axis=0)
        self.assertLess(after[0], now[0])
        self.assertLess(after[1], now[1])
        self.assertGreater(after[2], now[2])


if __name__ == "__main__":
    unittest.main()
