"""Standard prize structures, for when the player does not read out the real payouts."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pushfold import icm, structures  # noqa: E402


class MttCurveTest(unittest.TestCase):
    def test_pays_out_the_whole_pool_to_the_places_paid(self):
        for entrants, paid in ((1000, 150), (180, 27), (45, 7), (9, 3), (2, 1)):
            with self.subTest(entrants=entrants, paid=paid):
                prizes = structures.mtt(entrants, paid)
                self.assertEqual(len(prizes), paid)
                self.assertAlmostEqual(sum(prizes), entrants, places=6)

    def test_never_pays_less_for_a_better_place(self):
        prizes = np.array(structures.mtt(1000, 150))
        self.assertTrue(np.all(np.diff(prizes) <= 1e-12))
        self.assertGreater(prizes[0], prizes[1])

    def test_looks_like_a_real_big_field(self):
        prizes = np.array(structures.mtt(1000, 150)) / 1000
        self.assertTrue(0.12 <= prizes[0] <= 0.22)          # 1st: 12-22% of the pool
        self.assertTrue(1.3 <= prizes[0] / prizes[1] <= 2.2)
        self.assertAlmostEqual(prizes[-1] * 1000, structures.MIN_CASH, places=6)

    def test_small_payouts_use_the_usual_sit_and_go_splits(self):
        self.assertEqual(structures.mtt(9, 3), (4.5, 2.7, 1.8))
        self.assertEqual(structures.mtt(6, 2), (3.9, 2.1))
        self.assertEqual(structures.mtt(2, 1), (2.0,))

    def test_min_cash_shrinks_when_almost_everyone_is_paid(self):
        prizes = structures.mtt(10, 8)
        self.assertLess(prizes[-1], structures.MIN_CASH)
        self.assertAlmostEqual(sum(prizes), 10, places=6)

    def test_rejects_impossible_fields(self):
        for entrants, paid in ((10, 11), (10, 0), (0, 0)):
            with self.subTest(entrants=entrants, paid=paid), self.assertRaises(icm.PayoutError):
                structures.mtt(entrants, paid)


class StageTest(unittest.TestCase):
    def test_half_the_field_left(self):
        stage = structures.Stage(entrants=1000, left=500)
        self.assertEqual((stage.paid, stage.in_money), (150, False))
        self.assertEqual(len(stage.prizes()), 150)

    def test_in_the_money_only_the_places_still_open_count(self):
        stage = structures.Stage(entrants=1000, left=100)
        self.assertTrue(stage.in_money)
        prizes = stage.prizes()
        self.assertEqual(len(prizes), 100)
        self.assertEqual(prizes, structures.mtt(1000, 150)[:100])

    def test_payouts_put_everyone_away_from_the_table_in_the_crowd(self):
        p = structures.Stage(entrants=1000, left=500).payouts(table=8, crowd_stack=25.0)
        self.assertEqual((p.crowd, p.crowd_stack, len(p.prizes)), (492, 25.0, 150))

    def test_given_prizes_replace_the_standard_curve(self):
        stage = structures.Stage(entrants=100, left=12, given=(30, 20, 14, 10, 8, 6, 5, 4, 3))
        self.assertEqual(stage.paid, 9)
        self.assertEqual(stage.prizes(), (30, 20, 14, 10, 8, 6, 5, 4, 3))

    def test_the_bubble_is_a_few_players_above_the_money(self):
        self.assertEqual(structures.Stage.bubble(1000).left, 155)
        self.assertEqual(structures.Stage.bubble(9, given=(50, 30, 20)).left, 4)
        self.assertEqual(structures.Stage.bubble(4, given=(50, 30, 20, 10)).left, 4)  # all paid

    def test_rejects_stages_that_cannot_be(self):
        for kwargs in (dict(entrants=100, left=0), dict(entrants=100, left=101),
                       dict(entrants=100, left=50, paid_share=0.0)):
            with self.subTest(**kwargs), self.assertRaises(icm.PayoutError):
                structures.Stage(**kwargs)

    def test_fewer_left_than_seated_fails_clearly(self):
        with self.assertRaisesRegex(icm.PayoutError, "left"):
            structures.Stage(entrants=100, left=5).payouts(table=8, crowd_stack=10.0)


if __name__ == "__main__":
    unittest.main()
