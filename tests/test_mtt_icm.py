from __future__ import annotations

import itertools
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import numpy as np

from plo_premium_proof.finaltable import FinalTableSpec, SpecError, icm_table, solve
from plo_premium_proof.fullkernels import _utility, icm_equity, no_outcomes, scratch_size
from plo_premium_proof.fullsolve import CHIP_EV
from plo_premium_proof.fulltree import FullTree, FullTreeConfig
from plo_premium_proof.mtticm import build, layer_outcomes
from pushfold.icm import Payouts, value

MONSTER = ((1531.94, 1136.36, 842.99, 625.36, 463.91, 344.15, 255.30, 178.18) + (146.48,) * 2
           + (120.41,) * 3 + (98.99,) * 4 + (81.38,) * 7 + (66.90,) * 10 + (55.0,) * 17)


def brute_outcomes(masks):
    """Winner mask per layer for every ranking of the contenders, ties included."""
    seats = [s for s in range(16) if any(m >> s & 1 for m in masks)]
    found = set()
    for ranks in itertools.product(range(len(seats)), repeat=len(seats)):
        rank = dict(zip(seats, ranks))
        row = []
        for mask in masks:
            members = [s for s in seats if mask >> s & 1]
            best = min((rank[s] for s in members), default=None)
            row.append(sum(1 << s for s in members if rank[s] == best))
        found.add(tuple(row))
    return found


def random_ranks(rng, seats):
    return rng.integers(0, 3, size=seats).astype(np.int64)  # few values: ties are common


class LayerOutcomeTest(unittest.TestCase):
    def test_matches_every_ranking(self):
        for masks in [(0b111,), (0b1111, 0b1111, 0b0110), (0b11111, 0b11011, 0b01010, 0b01000),
                      (0b1011, 0b0011, 0b0001), (0b110, 0, 0b100), (0b1,)]:
            with self.subTest(masks=masks):
                got = layer_outcomes(masks)
                self.assertEqual(len(got), len(set(got)))
                self.assertEqual(set(got), brute_outcomes(masks))


class OutcomeTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = FullTree.build(FullTreeConfig(stacks=(6.0, 3.0, 9.0, 4.5), raise_caps=(2, 1, 0, 0),
                                                 ante_bb=0.1), cache_dir=None)

    def _final(self, node, ranks):
        tree = self.tree
        scratch = np.empty(scratch_size(tree.seats))
        return np.asarray([tree.start_stacks[s] + _utility(
            node, s, tree.start_stacks, tree.behind, tree.sidepot_count, tree.sidepot_amount,
            tree.sidepot_eligible_mask, ranks, CHIP_EV, scratch, *no_outcomes()) for s in range(tree.seats)])

    def _check(self, payouts, samples=400):
        tree = self.tree
        table = build(tree, payouts)
        rng = np.random.default_rng(3)
        terminals = np.flatnonzero(tree.actor < 0)
        start = tuple(tree.start_stacks)
        scratch = np.empty(scratch_size(tree.seats))
        for node in rng.choice(terminals, size=samples):
            ranks = random_ranks(rng, tree.seats)
            want = value(self._final(node, ranks), start, payouts)[0]
            for seat in range(tree.seats):
                got = _utility(node, seat, tree.start_stacks, tree.behind, tree.sidepot_count,
                               tree.sidepot_amount, tree.sidepot_eligible_mask, ranks, CHIP_EV, scratch,
                               table.start, table.winners, table.values)
                self.assertAlmostEqual(got, want[seat], places=6)

    def test_crowd_icm_matches_pricing_each_ending(self):
        self._check(Payouts(prizes=(40, 25, 15, 10, 6, 4), crowd=8, crowd_stack=5.0))

    def test_table_only_matches_the_final_table_kernel(self):
        tree, prizes = self.tree, np.asarray([50.0, 30, 20])
        table = build(tree, Payouts(prizes=tuple(prizes)))
        to_money = prizes.sum() / tree.start_stacks.sum()
        rng = np.random.default_rng(5)
        scratch = np.empty(scratch_size(tree.seats))
        for node in rng.choice(np.flatnonzero(tree.actor < 0), size=300):
            ranks = random_ranks(rng, tree.seats)
            for seat in range(tree.seats):
                direct = _utility(node, seat, tree.start_stacks, tree.behind, tree.sidepot_count,
                                  tree.sidepot_amount, tree.sidepot_eligible_mask, ranks, prizes, scratch,
                                  *no_outcomes())
                looked = _utility(node, seat, tree.start_stacks, tree.behind, tree.sidepot_count,
                                  tree.sidepot_amount, tree.sidepot_eligible_mask, ranks, CHIP_EV, scratch,
                                  table.start, table.winners, table.values)
                self.assertAlmostEqual(looked * to_money, direct, places=6)

    def test_crowd_of_one_stack_equals_listing_everyone(self):
        stacks = np.asarray([[6.0, 3.0, 9.0]])
        crowd = Payouts(prizes=(50, 30, 20, 10), crowd=2, crowd_stack=4.0)
        listed = Payouts(prizes=(50, 30, 20, 10), field=(4.0, 4.0))
        np.testing.assert_allclose(value(stacks, (6, 3, 9), crowd), value(stacks, (6, 3, 9), listed))
        work = np.empty(scratch_size(5))
        everyone = np.asarray([6.0, 3.0, 9.0, 4.0, 4.0])
        scale = 26.0 / 110.0
        want = [icm_equity(everyone, everyone, np.asarray([50.0, 30, 20, 10]) * scale, s, work) for s in range(3)]
        np.testing.assert_allclose(value(stacks, (6, 3, 9), crowd)[0], want)


class MttSpecTest(unittest.TestCase):
    def test_field_and_validation(self):
        spec = FinalTableSpec(stacks=(30, 12, 55, 20, 8, 41), payouts=MONSTER, players_left=60,
                              field_stack_bb=31.0)
        self.assertTrue(spec.is_mtt)
        self.assertEqual(spec.field_payouts.crowd, 54)
        self.assertEqual(len(spec.field_payouts.prizes), 51)
        self.assertFalse(FinalTableSpec(stacks=(30, 12, 55), payouts=MONSTER, players_left=3).is_mtt)
        for bad in ({"players_left": 4}, {"players_left": 60, "field_stack_bb": 0.0}):
            with self.subTest(bad=bad), self.assertRaises(SpecError):
                FinalTableSpec(stacks=(30, 12, 55, 20, 8, 41), payouts=MONSTER, **bad)

    def test_icm_table_in_money_sums_to_the_table_share(self):
        spec = FinalTableSpec(stacks=(30, 12, 55, 20, 8, 41), payouts=MONSTER, players_left=60,
                              field_stack_bb=31.0)
        equity = icm_table(spec.stacks, spec.prizes, spec.field_payouts)
        order = np.argsort(spec.stacks)
        self.assertTrue(np.all(np.diff(np.asarray(equity)[order]) > 0))   # more chips, more money
        self.assertLess(min(equity), 55.0)              # 8bb nine from the money may still miss it
        self.assertLess(sum(equity), sum(MONSTER))

    def test_short_mtt_solve(self):
        spec = FinalTableSpec(stacks=(4.0, 2.5, 6.0), payouts=(50, 30, 20, 10), ante_bb=0.1,
                              raise_caps=(2, 1, 0, 0), minutes=0.5, threads=2, players_left=9,
                              field_stack_bb=5.0, label="test spot")
        ticks = itertools.count(step=10.0)
        with tempfile.TemporaryDirectory() as folder:
            out = pathlib.Path(folder)
            status = solve(spec, out, epoch_deals=200, clock=lambda: next(ticks))
            self.assertEqual(status["state"], "done")
            self.assertGreater(status["outcomes"], 0)
            result = json.loads((out / "result.json").read_text())
            self.assertEqual(result["label"], "test spot")
            self.assertIn("field avg 5bb", result["detail"])
            self.assertLess(sum(result["icm"]), 110.0)

    def test_solves_do_not_cache_their_tree(self):
        spec = FinalTableSpec(stacks=(4.0, 2.5, 6.0), payouts=(50, 30, 20), raise_caps=(2, 1, 0, 0),
                              minutes=0.5, threads=2)
        ticks = itertools.count(step=40.0)
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(FullTree, "build", wraps=FullTree.build) as build:
            solve(spec, pathlib.Path(folder), epoch_deals=50, clock=lambda: next(ticks))
        self.assertIsNone(build.call_args.kwargs.get("cache_dir", "missing"))


if __name__ == "__main__":
    unittest.main()
