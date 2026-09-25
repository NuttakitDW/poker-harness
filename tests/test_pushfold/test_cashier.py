"""M4: the Cashier pays out every ending, checked against pokerkit's own side pots."""

import random
import sys
import unittest
from pathlib import Path

import numpy as np
from pokerkit import Automation, NoLimitTexasHoldem

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pushfold import cashier, floor, oddsmaker  # noqa: E402
from pushfold.spot import Spot  # noqa: E402

RANKS, SUITS = "23456789TJQKA", "cdhs"


def text(card: int) -> str:
    return RANKS[card // 4] + SUITS[card % 4]


class LayerTest(unittest.TestCase):
    def test_shove_folded_to(self):
        spot = Spot((10, 10, 10), ante=0.1)
        net = cashier.settle(spot, jammers=(0,)).net_for({0: 1})
        np.testing.assert_allclose(net, [1.7, -0.6, -1.1])

    def test_walk(self):
        net = cashier.settle(Spot((10, 10)), jammers=()).net_for({1: 1})
        np.testing.assert_allclose(net, [-0.5, 0.5])

    def test_deep_stack_is_capped_at_the_effective_stack(self):
        deep = cashier.settle(Spot((100, 10)), jammers=(0, 1))
        even = cashier.settle(Spot((10, 10)), jammers=(0, 1))
        for winner in (0, 1):
            np.testing.assert_allclose(deep.net_for({winner: 1, 1 - winner: 2}),
                                       even.net_for({winner: 1, 1 - winner: 2}))

    def test_three_way_side_pot(self):
        # Short BTN 3bb, SB 10bb, BB 20bb, all in. Main 9bb three ways, side 14bb SB vs BB.
        s = cashier.settle(Spot((3, 10, 20)), jammers=(0, 1, 2))
        self.assertEqual([(round(l.amount, 9), l.eligible) for l in s.layers],
                         [(9.0, (0, 1, 2)), (14.0, (1, 2))])
        np.testing.assert_allclose(s.net_for({0: 1, 1: 3, 2: 2}), [6, -10, 4])

    def test_zero_sum_on_every_terminal(self):
        rng = np.random.default_rng(5)
        for _ in range(200):
            n = int(rng.integers(2, 10))
            spot = Spot(tuple(rng.uniform(1.5, 15, n).round(2)), ante=float(rng.choice([0, 0.1, 0.125])))
            for t in floor.build(spot).terminals:
                ranks = {seat: int(rng.integers(0, 3)) for seat in t.alive}
                self.assertAlmostEqual(float(cashier.settle(spot, t.jammers).net_for(ranks).sum()), 0, places=9)


def pokerkit_net(spot_chips, blinds, ante, ante_mode, actions, holes, board):
    """Play the same all-in sequence in pokerkit, return net chips in our seat order."""
    n = len(spot_chips)
    ours_to_pk = {0: 1, 1: 0} if n == 2 else {**{n - 2: 0, n - 1: 1}, **{p: p + 2 for p in range(n - 2)}}
    pk_to_ours = {v: k for k, v in ours_to_pk.items()}
    stacks = [spot_chips[pk_to_ours[i]] for i in range(n)]
    antes = ante if ante_mode == "each" else {1: ante}  # pokerkit: blind-position index, even heads-up
    state = NoLimitTexasHoldem.create_state(
        (Automation.ANTE_POSTING, Automation.BET_COLLECTION, Automation.BLIND_OR_STRADDLE_POSTING,
         Automation.CARD_BURNING, Automation.HOLE_CARDS_SHOWING_OR_MUCKING, Automation.HAND_KILLING,
         Automation.CHIPS_PUSHING, Automation.CHIPS_PULLING),
        False, antes, blinds, blinds[1], stacks, n)
    for i in range(n):
        state.deal_hole("".join(text(c) for c in holes[pk_to_ours[i]]))
    for seat, action in enumerate(actions):
        if action == floor.IDLE or not state.status or state.actor_index is None:
            continue
        assert state.actor_index == ours_to_pk[seat], (state.actor_index, seat)
        if action == floor.FOLD:
            state.fold()
        elif state.can_complete_bet_or_raise_to():
            state.complete_bet_or_raise_to(state.max_completion_betting_or_raising_to_amount)
        else:
            state.check_or_call()
    while state.status:
        state.deal_board(text(board[len(state.board_cards)]))
    return np.array([state.payoffs[ours_to_pk[p]] for p in range(n)], dtype=float)


class PokerkitCrossCheck(unittest.TestCase):
    def test_random_all_ins_match_pokerkit(self):
        rng = random.Random(9)
        checked = 0
        for _ in range(300):
            n = rng.randint(2, 7)
            mode = rng.choice(["each", "bb"])
            ante = rng.choice([0, 10, 25]) if mode == "each" else rng.choice([0, 100])
            chips = tuple(rng.randint(250, 2000) for _ in range(n))
            spot = Spot(tuple(c / 100 for c in chips), ante=ante / 100, ante_mode=mode)
            tree = floor.build(spot, max_allin=n)
            terminal = rng.choice(tree.terminals)
            deck = rng.sample(range(52), 2 * n + 5)
            holes = [tuple(deck[2 * i:2 * i + 2]) for i in range(n)]
            board = deck[2 * n:]
            ours = cashier.settle(spot, terminal.jammers)
            alive = terminal.alive
            strength = oddsmaker.strength(np.array([holes[s] for s in alive]),
                                          np.array([board] * len(alive)))
            order = sorted(set(strength.tolist()), reverse=True)
            ranks = {seat: order.index(int(v)) + 1 for seat, v in zip(alive, strength)}
            want = pokerkit_net(chips, (50, 100), ante, mode, terminal.actions, holes, board)
            # pokerkit pays whole chips; odd chips on split pots may differ by 1.
            np.testing.assert_allclose(ours.net_for(ranks) * 100, want, atol=1.01,
                                       err_msg=f"{spot} {terminal.actions} {ranks}")
            checked += 1
        self.assertEqual(checked, 300)


if __name__ == "__main__":
    unittest.main()
