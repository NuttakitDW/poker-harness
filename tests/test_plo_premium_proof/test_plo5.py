"""PLO5 support: the hand-history reader, five-card showdowns and the preflop bucket split."""

from __future__ import annotations

import unittest

import numpy as np

from plo_equity.cards import parse_cards
from plo_premium_proof.hh import parse_hand
from plo_premium_proof.kernels import plo_rank
from plo_premium_proof.plo5 import class_buckets, weighted_cuts
from plo_premium_proof.tables import comb_table, five_card_ranks

HAND = """Poker Hand #TM1: Tournament #2, PLO-5 Classic $10 Omaha5 Pot Limit - Level16(800/1,600(200)) - 2026/10/07 10:26:34
Table '8' 6-max Seat #5 is the button
Seat 1: Hero (16,381 in chips)
Seat 3: aa (94,886 in chips)
Seat 4: bb (28,674 in chips)
Seat 5: cc (20,294 in chips)
Seat 6: dd (110,764 in chips)
Hero: posts the ante 200
aa: posts the ante 200
bb: posts the ante 200
cc: posts the ante 200
dd: posts the ante 200
dd: posts small blind 800
Hero: posts big blind 1,600
*** HOLE CARDS ***
Dealt to Hero [6s 3h Kc Qs 4c]
aa: folds
bb: folds
cc: calls 1,600
dd: folds
Hero: checks
*** FLOP *** [Td Qh 7c]
Hero: checks
cc: bets 5,000
Hero: raises 9,581 to 14,581 and is all-in
cc: calls 9,581
*** TURN *** [Td Qh 7c] [7s]
*** RIVER *** [Td Qh 7c 7s] [Jh]
*** SHOWDOWN ***
cc collected 34,162 from pot
*** SUMMARY ***
"""


class Plo5Test(unittest.TestCase):
    def test_hand_history_in_preflop_order(self) -> None:
        hand = parse_hand(HAND)
        self.assertEqual(hand.players, ("aa", "bb", "cc", "dd", "Hero"))  # UTG ... BTN, SB, BB
        self.assertEqual(hand.hero, 4)
        self.assertAlmostEqual(hand.stacks_bb[hand.hero], 16381 / 1600)
        self.assertEqual(len(hand.hero_cards), 5)
        self.assertEqual(len(hand.board), 5)
        raise_ = [a for a in hand.actions if a.kind == "raise"][0]
        self.assertEqual((raise_.street, raise_.amount, raise_.all_in), (1, 14581, True))
        self.assertEqual(hand.table, "8")

    def test_five_card_showdown_uses_exactly_two_hole_cards(self) -> None:
        rank5, comb = five_card_ranks(), comb_table()
        board = np.asarray(parse_cards("AhKhQh2c3d"), dtype=np.int64)
        flush = np.asarray(parse_cards("JhTh4c5c6d"), dtype=np.int64)   # royal flush with two hearts
        one_heart = np.asarray(parse_cards("Jh4c5c6d7s"), dtype=np.int64)  # one heart cannot make a flush
        self.assertLess(plo_rank(flush, board, rank5, comb), plo_rank(one_heart, board, rank5, comb))
        four = np.asarray(parse_cards("JhTh4c5c"), dtype=np.int64)
        self.assertEqual(plo_rank(flush, board, rank5, comb), plo_rank(four, board, rank5, comb))

    def test_buckets_split_bands_by_weight(self) -> None:
        rng = np.random.default_rng(0)
        eq = rng.random((5000, 2))
        combos = rng.integers(4, 120, size=5000)
        bucket = class_buckets(eq, combos)
        self.assertEqual(int(bucket.min()), 0)
        self.assertLessEqual(int(bucket.max()), 999)
        cuts = weighted_cuts(eq[:, 0], combos.astype(float), 4)
        self.assertEqual(len(cuts), 3)


if __name__ == "__main__":
    unittest.main()
