"""Checks for the exact physical-hand census of the PLO tier classifier."""

from pathlib import Path
import importlib.util
import math
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_plo_vpip", ROOT / "scripts" / "analyze_plo_vpip.py")
assert SPEC and SPEC.loader
analyze_plo_vpip = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze_plo_vpip)


class CensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = analyze_plo_vpip.census()

    def test_every_physical_hand_has_equal_weight(self):
        expected = math.comb(52, 4)
        self.assertEqual(self.report["total_combinations"], expected)
        self.assertEqual(sum(row["count"] for row in self.report["tiers"].values()), expected)
        self.assertAlmostEqual(
            sum(row["percent"] for row in self.report["tiers"].values()), 100, places=5)

    def test_rank_pattern_population_matches_card_combinatorics(self):
        counts = {name: row["count"] for name, row in self.report["rank_patterns"].items()}
        self.assertEqual(counts, {
            "four_distinct_ranks": math.comb(13, 4) * 4**4,
            "one_pair": 13 * math.comb(4, 2) * math.comb(12, 2) * 4**2,
            "quads": 13,
            "trips": 13 * math.comb(4, 3) * 12 * 4,
            "two_pair": math.comb(13, 2) * math.comb(4, 2)**2,
        })

    def test_trips_quads_and_suit_edges_are_explicit(self):
        edges = self.report["edge_cases"]
        self.assertEqual((edges["trips"]["form"], edges["trips"]["tier"]), ("trips", "Trash"))
        self.assertEqual((edges["quads"]["form"], edges["quads"]["tier"]), ("trips", "Trash"))
        self.assertEqual(edges["four_to_one_suit"]["classifier_shape"], "single-suited")
        self.assertEqual(edges["double_suited"]["classifier_shape"], "double-suited")
        self.assertFalse(edges["ace_outside_suited_group"]["ace_suited"])

    def test_inventory_does_not_claim_solver_or_vpip_result(self):
        joined = " ".join(self.report["limitations"]).lower()
        self.assertIn("not vpip", joined)
        self.assertIn("no solver", joined)

    def test_confirmed_chip_ev_assumptions_are_recorded(self):
        assumptions = self.report["assumptions"]
        self.assertEqual(assumptions["format"], "six-max tournament chip EV; seats do not affect this inventory")
        self.assertEqual(assumptions["effective_stack_bb"], 100)
        self.assertEqual(assumptions["starting_stacks"], "six equal 100bb stacks")
        self.assertEqual(assumptions["ante"], 0)
        self.assertEqual(assumptions["rake"], 0)
        self.assertIn("no payout or ICM adjustment", assumptions["tournament_payouts"])


if __name__ == "__main__":
    unittest.main()
