import math
import random
import unittest

from plo_thesis_audit.statistics import (
    hoeffding_bound,
    rejection_sample,
    surrogate_hoeffding_bound,
)


class StatisticsTest(unittest.TestCase):
    def test_constant_x_uses_familywide_one_sided_hoeffding_k(self):
        bound = hoeffding_bound(mean_x=0.25, accepted=50_000, cells=36, alpha=0.05)
        one_tail = math.sqrt(math.log(36 / 0.05) / (2 * 50_000))
        two_tail = math.sqrt(math.log(2 * 36 / 0.05) / (2 * 50_000))

        self.assertAlmostEqual(bound.one_sided_radius_x, one_tail)
        self.assertAlmostEqual(
            bound.lower_true_deviation_gain_bb,
            2 * (0.25 - one_tail) - 0.5,
        )
        self.assertAlmostEqual(
            bound.upper_conservative_surrogate_bb,
            2 * (0.25 + one_tail) - 0.5,
        )
        self.assertAlmostEqual(bound.two_sided_surrogate_radius_x, two_tail)
        self.assertAlmostEqual(
            bound.two_sided_surrogate_lower_bb,
            2 * (0.25 - two_tail) - 0.5,
        )
        self.assertAlmostEqual(
            bound.two_sided_surrogate_upper_bb,
            2 * (0.25 + two_tail) - 0.5,
        )
        self.assertEqual(bound.familywise_alpha, 0.05)
        self.assertEqual(bound.simultaneous_cells, 36)
        self.assertIn("not an upper bound on true", bound.interpretation)

    def test_global_range_one_uses_k_for_one_tail_and_2k_for_two_tail(self):
        bound = surrogate_hoeffding_bound(
            mean_surrogate_bb=0.01,
            samples=1_000_000,
            cells=5,
            alpha=0.05,
            sample_lower_bb=-0.5,
            sample_upper_bb=0.5,
        )
        one_tail = math.sqrt(math.log(5 / 0.05) / (2 * 1_000_000))
        two_tail = math.sqrt(math.log(2 * 5 / 0.05) / (2 * 1_000_000))

        self.assertAlmostEqual(bound.one_sided_radius_bb, one_tail)
        self.assertAlmostEqual(bound.two_sided_surrogate_radius_bb, two_tail)
        self.assertAlmostEqual(bound.lower_true_deviation_gain_bb, 0.01 - one_tail)
        self.assertAlmostEqual(bound.two_sided_surrogate_upper_bb, 0.01 + two_tail)

    def test_rejection_sampling_matches_small_exact_conditional_distribution(self):
        # Uniform draws from 0..5 conditioned on even values are exactly uniform on 0,2,4.
        samples, draws = rejection_sample(
            random.Random(7301),
            draw=lambda rng: rng.randrange(6),
            accept=lambda value: value % 2 == 0,
            target=30_000,
        )

        frequencies = {value: samples.count(value) / len(samples) for value in (0, 2, 4)}
        self.assertEqual(set(samples), {0, 2, 4})
        self.assertTrue(all(abs(frequency - 1 / 3) < 0.012 for frequency in frequencies.values()))
        self.assertGreater(draws, len(samples))
