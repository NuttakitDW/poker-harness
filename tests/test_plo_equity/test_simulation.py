import unittest

from plo_equity.cards import canonical_hand, parse_hand
from plo_equity.simulation import TrialStats, deal_block, simulate_range


class SimulationTest(unittest.TestCase):
    def setUp(self):
        self.hero = canonical_hand(parse_hand("AsAhKsKh"))

    def test_deals_are_disjoint_and_reproducible(self):
        first = deal_block(self.hero, global_seed=17, block_index=3, opponents=5)
        second = deal_block(self.hero, global_seed=17, block_index=3, opponents=5)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1_000)
        for dealt in first[:25]:
            self.assertEqual(len(dealt), 25)
            self.assertFalse(set(dealt) & set(self.hero))
            self.assertEqual(len(set(dealt)), len(dealt))

    def test_interrupted_resume_is_bit_identical(self):
        whole = simulate_range(self.hero, 0, 250, global_seed=29, opponents=1)
        first = simulate_range(self.hero, 0, 100, global_seed=29, opponents=1)
        rest = simulate_range(self.hero, 100, 250, global_seed=29, opponents=1)
        self.assertEqual(whole, first + rest)

    def test_fractional_ties_and_standard_error(self):
        stats = TrialStats(2, 1.5, 1.25, 1, 1)
        self.assertEqual((stats.equity, stats.win_rate, stats.tie_rate), (.75, .5, .5))
        self.assertAlmostEqual(stats.standard_error, .25)
