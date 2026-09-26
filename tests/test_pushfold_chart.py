"""Checks that short tournament stacks get a solved push/fold chart in make chart."""

from pathlib import Path
import re
import sys
import dataclasses
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "tests"))
import preflop  # noqa: E402
import pushfold_chart  # noqa: E402
import spot_chart  # noqa: E402
from test_preflop import book, chart  # noqa: E402
from test_spot import SpotTestCase  # noqa: E402

ANSI = re.compile(r"\033\[[0-9;]*m")


def request(**fields):
    return preflop.Request(**{"game": "tournament", "stack": 10, "hero": "BTN", **fields})


class RoutingTests(unittest.TestCase):
    def test_short_tournament_stack_goes_to_the_solver(self):
        self.assertTrue(pushfold_chart.applies(request()))

    def test_the_boundary_is_fifteen_big_blinds(self):
        self.assertTrue(pushfold_chart.applies(request(stack=15)))
        self.assertFalse(pushfold_chart.applies(request(stack=16)))

    def test_cash_and_unstated_stacks_keep_the_book_charts(self):
        self.assertFalse(pushfold_chart.applies(request(game="cash")))
        self.assertFalse(pushfold_chart.applies(request(stack=None)))

    def test_stacks_below_three_bb_are_solved(self):
        made = pushfold_chart.solved(request(hero="UTG", stack=1.5))
        self.assertEqual(made.chart["stack"], 1.5)

    def test_a_hero_all_in_by_posting_has_no_decision(self):
        self.assertTrue(pushfold_chart.all_in_by_posting(request(hero="BB", stack=1)))
        self.assertFalse(pushfold_chart.all_in_by_posting(request(hero="UTG", stack=1)))
        self.assertIsNone(pushfold_chart.solved(request(hero="BB", stack=1)))


class ThaiSpellingTests(unittest.TestCase):
    """Real Discord voice messages: English seat words written the way they sound in Thai."""

    def test_a_button_open_jam_asked_from_the_small_blind(self):
        made = preflop.parse("ขอ 12.2 บิ๊กบาย บัตท่อนโอเพ่นมา โอเพ่นแจมมา สมอลไบล์ทํายังไง")
        self.assertEqual((made.stack, made.hero, made.villain), (12.2, "SB", "BTN"))
        self.assertTrue(made.pushfold)

    def test_two_jams_asked_from_the_big_blind(self):
        made = preflop.parse("10 บิ๊กไบร์ท UTG แจม บัตท่อนแจม มาถึงตําแหน่งบิ๊กไบร์ท.")
        self.assertEqual((made.stack, made.hero, made.shovers), (10, "BB", ("UTG", "BTN")))

    def test_other_sounded_out_spellings_are_read(self):
        for said, seat in (("บัตทอน shove 10bb", "BTN"), ("สมอลไบ shove 10bb", "SB"),
                           ("บิ๊กไบล์ เจอ SB ออลอิน 8bb", "BB"), ("สมอลบลายด์ shove 10bb", "SB")):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).hero, seat)

    def test_a_sounded_out_big_blind_after_a_number_is_the_stack(self):
        self.assertEqual(preflop.parse("BTN ออลอิน 8 บิ๊กไบร์ท").stack, 8)
        self.assertEqual(preflop.parse("BTN ออลอิน 8 บิ๊กไบร์ท").hero, "BTN")


class SpokenHandTests(unittest.TestCase):
    """Voice transcripts name the cards in words: "Jack 2 off", "แจ็ค 2 ออฟ"."""

    def test_card_names_and_off_are_read_as_a_hand(self):
        for said, hands in (("Jack 2 off.", ["J2o"]), ("Ace King suited", ["AKs"]),
                            ("แจ็ค 2 ออฟ", ["J2o"]), ("ถือ คิง ควีน", ["KQs", "KQo"]),
                            ("pocket jacks", ["JJ"]), ("Queen ten off", ["QTo"]),
                            ("เอซ 5 suit", ["A5s"])):
            with self.subTest(said=said):
                self.assertEqual(preflop.hands_in(said), hands)

    def test_ten_big_blinds_is_not_a_hand(self):
        self.assertEqual(preflop.hands_in("BTN shove ten big blinds"), [])

    def test_a_hand_alone_follows_up_on_the_last_chart(self):
        _, first = spot_chart.answer("4.4bb บัตท่อน แจม บิ๊กบายทำอะไร", color=False)
        text, found = spot_chart.answer("Jack 2 off.", color=False, memory=first.request)
        self.assertEqual(found.hands, ("J2o",))
        self.assertIn("J2o = ", text)


class DecimalStackTests(unittest.TestCase):
    def test_a_decimal_stack_is_read(self):
        for said, stack in (("SB shove 5.5bb", 5.5), ("BTN ออลอิน 7.25 บีบี", 7.25),
                            ("BB vs SB 12.5 big blinds", 12.5)):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).stack, stack)

    def test_whole_stacks_stay_whole_numbers(self):
        self.assertEqual(preflop.parse("BTN shove 10bb").stack, 10)
        self.assertIsInstance(preflop.parse("BTN shove 10.0bb").stack, int)

    def test_a_decimal_stack_is_solved_at_that_depth(self):
        made = pushfold_chart.solved(request(hero="SB", stack=5.5))
        self.assertEqual(made.chart["stack"], 5.5)
        self.assertIn("all stacks 5.5bb", made.note)


class AnteTests(unittest.TestCase):
    def test_an_ante_is_read_as_a_share_of_the_big_blind(self):
        for said, ante in (("BTN shove 10bb ante 12.5%", 0.125), ("BTN 10bb ante 0.2bb", 0.2),
                           ("BTN 10bb ante 20", 0.2), ("BTN 10bb แอนตี้ 15%", 0.15),
                           ("BTN 10bb no ante", 0.0), ("BTN 10bb ไม่มี ante", 0.0)):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).ante, ante)

    def test_the_ante_amount_is_not_read_as_the_stack(self):
        self.assertEqual(preflop.parse("BTN 10bb ante 0.2bb").stack, 10)
        self.assertIsNone(preflop.parse("ante 0.2bb").stack)

    def test_no_ante_mentioned_stays_unknown(self):
        self.assertIsNone(preflop.parse("BTN 10bb").ante)

    def test_a_follow_up_keeps_the_ante(self):
        import spot
        merged = spot.merge(preflop.Request(stack=8), preflop.Request(ante=0.2, hero="BTN"))
        self.assertEqual(merged.ante, 0.2)

    def test_everyone_antes_ten_percent_by_default(self):
        made = pushfold_chart.solved(request(stack=10))
        self.assertIn("ante 0.1bb each", made.note)

    def test_the_stated_stack_is_what_is_left_after_the_ante(self):
        self.assertEqual(pushfold_chart.table(request(stack=1.5)).stacks[0], 1.6)
        self.assertEqual(pushfold_chart.table(request(stack=1.5, ante=0.0)).stacks[0], 1.5)

    def test_a_one_and_a_half_bb_big_blind_still_has_a_decision(self):
        self.assertFalse(pushfold_chart.all_in_by_posting(request(hero="BB", stack=1.5)))
        self.assertIsNotNone(pushfold_chart.solved(request(hero="BB", stack=1.5)))

    def test_a_big_blind_with_less_than_the_blind_behind_is_all_in(self):
        self.assertTrue(pushfold_chart.all_in_by_posting(request(hero="BB", stack=0.8)))


class SeatAtTableTests(unittest.TestCase):
    def test_a_seat_missing_at_that_table_size_is_named_with_the_seats_there(self):
        self.assertEqual(pushfold_chart.missing_seat(request(hero="UTG", stack=5, players=4)),
                         ("UTG", ("CO", "BTN", "SB", "BB")))

    def test_a_shover_missing_at_that_table_size_is_caught_too(self):
        missing = pushfold_chart.missing_seat(request(hero="BB", villain="UTG", shovers=("UTG",),
                                                      stack=5, players=4))
        self.assertEqual(missing[0], "UTG")

    def test_seats_that_exist_are_fine(self):
        self.assertIsNone(pushfold_chart.missing_seat(request(hero="CO", stack=5, players=4)))
        self.assertIsNone(pushfold_chart.missing_seat(request(hero="BTN", stack=5, players=2)))


class BigBlindAnteTests(unittest.TestCase):
    def test_bb_ante_and_live_switch_to_the_big_blind_paying_for_the_table(self):
        for said in ("BTN shove 10bb bb ante", "BTN shove 10bb big blind ante",
                     "BTN shove 10bb live tournament", "BTN ออลอิน 10bb ทัวร์ live", "BTN 10bb BB-ante"):
            with self.subTest(said=said):
                made = preflop.parse(said)
                self.assertEqual(made.ante_mode, "bb")
                self.assertIsNone(made.ante)
                self.assertEqual((made.hero, made.stack), ("BTN", 10))

    def test_a_bb_ante_amount_without_a_unit_is_in_big_blinds(self):
        self.assertEqual(preflop.parse("BTN 10bb bb ante 1.5").ante, 1.5)
        self.assertEqual(preflop.parse("BTN 10bb bb ante 150%").ante, 1.5)

    def test_a_plain_ante_means_everyone_antes(self):
        self.assertEqual(preflop.parse("BTN 10bb ante 12.5%").ante_mode, "each")

    def test_the_bb_ante_defaults_to_one_big_blind(self):
        made = pushfold_chart.solved(request(stack=10, ante_mode="bb"))
        self.assertIn("BB ante 1bb", made.note)

    def test_only_the_big_blind_gets_its_ante_added_back(self):
        spot = pushfold_chart.table(request(stack=10, ante_mode="bb"))
        self.assertEqual(spot.stacks, (10.0,) * 7 + (11.0,))
        self.assertEqual(spot.antes, (0.0,) * 7 + (1.0,))

    def test_switching_to_bb_ante_drops_the_old_per_player_amount(self):
        import spot
        merged = spot.merge(preflop.Request(ante_mode="bb"),
                            preflop.Request(hero="BTN", ante=0.125, ante_mode="each"))
        self.assertEqual((merged.ante_mode, merged.ante), ("bb", None))


class TableSizeTests(unittest.TestCase):
    def test_heads_up_is_read_in_english_and_thai(self):
        for said in ("ขอเป็นแบบ Heads-up.", "heads up BTN 5bb", "HU 10bb", "เฮดอัพ 8bb",
                     "ตัวต่อตัว 8bb"):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).players, 2)

    def test_max_and_handed_are_read(self):
        self.assertEqual(preflop.parse("6-max CO 10bb").players, 6)
        self.assertEqual(preflop.parse("3 handed BTN 10bb").players, 3)
        self.assertEqual(preflop.parse("โต๊ะ 9 คน UTG 10bb").players, 9)

    def test_no_table_size_stays_unknown(self):
        self.assertIsNone(preflop.parse("BTN 10bb hush").players)

    def test_a_follow_up_keeps_the_table_size(self):
        import spot
        merged = spot.merge(preflop.Request(stack=8), preflop.Request(players=2, hero="BTN"))
        self.assertEqual(merged.players, 2)

    def test_a_seat_missing_from_the_remembered_table_starts_a_new_table(self):
        import spot
        memory = preflop.parse("aof 4 handed BB vs CO shove 10bb")
        merged = spot.merge(preflop.parse("ขอทัวร์ธรรมดา 14bb utg"), memory)
        self.assertIsNone(merged.players)
        self.assertFalse(merged.aof)
        self.assertEqual((merged.hero, merged.stack), ("UTG", 14))

    def test_a_seat_at_the_remembered_table_keeps_it(self):
        import spot
        merged = spot.merge(preflop.parse("CO 10bb"), preflop.parse("aof 4 handed BB 10bb"))
        self.assertEqual((merged.players, merged.aof), (4, True))

    def test_handed_typo_is_read(self):
        self.assertEqual(preflop.parse("13.2 bb UTG tournament 8 haned").players, 8)


class AskedForPushFoldTests(unittest.TestCase):
    def test_push_fold_words_are_read(self):
        for said in ("ขอฉาด Push/fold 16 Big blind", "SB call a jam 16bb", "BTN shove 20bb",
                     "UTG ออลอิน 18bb", "pushfold 16bb"):
            with self.subTest(said=said):
                self.assertTrue(preflop.parse(said).pushfold)

    def test_the_seat_that_jams_is_the_villain(self):
        for said in ("Call open jam จากตําแหน่ง small blind คน jam เป็น UTG",
                     "UTG jam แล้ว SB call ได้อะไร", "SB vs BTN shove 10bb",
                     "SB เจอ UTG ออลอิน 12bb"):
            with self.subTest(said=said):
                made = preflop.parse(said)
                self.assertEqual(made.scenario, "All-In")
                self.assertEqual(made.hero, "SB")
                self.assertIn(made.villain, ("UTG", "BTN"))

    def test_we_are_marks_the_hero_among_two_shovers(self):
        for said in ("UTG all-in 5 Big blind Button all-in 5 Big blind เราอยู่ small blind เราทํายังไง",
                     "UTG shove, BTN shove, I'm in the SB 5bb"):
            with self.subTest(said=said):
                made = preflop.parse(said)
                self.assertEqual((made.hero, made.scenario), ("SB", "All-In"))
                self.assertEqual(made.shovers, ("UTG", "BTN"))

    def test_a_seat_that_calls_the_jam_is_all_in_too(self):
        made = preflop.parse("เราอยู่ตําแหน่ง Small blind UTG all-in มา 5 BB เอ่อ แล้วก็ button call "
                             "เราต้องเล่นยังไง")
        self.assertEqual((made.hero, made.shovers), ("SB", ("UTG", "BTN")))

    def test_the_heros_own_call_is_the_question_not_a_shover(self):
        made = preflop.parse("Cutoff แจมมา 16 Big blind, small blind call ด้วยอะไร?")
        self.assertEqual((made.hero, made.shovers), ("SB", ("CO",)))

    def test_a_one_letter_seat_typo_is_still_read(self):
        for said, seat in (("sb เจอ BTBN all in 5bb", "BTN"), ("SB vs UGT shove 5bb", "UTG"),
                           ("BB vs cutof jam 8bb", "CO")):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).shovers, (seat,))

    def test_ordinary_words_are_not_read_as_seats(self):
        self.assertEqual(preflop.parse("SB but not the bin 5bb").hero, "SB")
        self.assertIsNone(preflop.parse("SB but not the bin 5bb").villain)

    def test_two_shovers_give_the_overcall_chart(self):
        made = pushfold_chart.solved(request(hero="SB", villain="UTG", shovers=("UTG", "BTN"),
                                             stack=5))
        self.assertEqual(made.chart["villain"], "UTG+BTN")
        self.assertEqual(made.chart["scenario"], "Call vs shove")

    def test_a_new_opponent_drops_the_old_shovers(self):
        import spot
        merged = spot.merge(preflop.Request(villain="CO"),
                            preflop.Request(hero="SB", villain="UTG", shovers=("UTG", "BTN")))
        self.assertEqual(merged.shovers, ())

    def test_a_lone_shover_is_still_first_in(self):
        made = preflop.parse("BTN shove 10bb")
        self.assertEqual((made.hero, made.villain, made.scenario), ("BTN", None, "RFI"))

    def test_an_open_is_not_push_fold(self):
        self.assertFalse(preflop.parse("UTG open 16bb tournament").pushfold)

    def test_asking_for_push_fold_lifts_the_fifteen_bb_limit(self):
        self.assertTrue(pushfold_chart.applies(request(stack=16, pushfold=True)))
        self.assertFalse(pushfold_chart.applies(request(stack=16)))

    def test_a_follow_up_keeps_the_push_fold_ask(self):
        import spot
        merged = spot.merge(preflop.Request(), preflop.Request(stack=16, pushfold=True))
        self.assertTrue(merged.pushfold)

    def test_deeper_than_fifteen_bb_the_note_warns(self):
        made = pushfold_chart.solved(request(hero="SB", villain="UTG", stack=16, pushfold=True))
        self.assertEqual(made.chart["stack"], 16)
        self.assertEqual(made.chart["scenario"], "Call vs shove")
        self.assertIn("above 15bb", made.note)


class HeadsUpTests(unittest.TestCase):
    def test_the_button_is_the_small_blind_heads_up(self):
        made = pushfold_chart.solved(request(hero="BTN", stack=5, players=2))
        self.assertIn("heads-up", made.note)
        self.assertEqual(made.chart["scenario"], "Push/Fold")
        self.assertEqual(made.chart["hero"], "BTN/SB")

    def test_the_big_blind_faces_the_button_heads_up(self):
        made = pushfold_chart.solved(request(hero="BB", villain="BTN", stack=5, players=2))
        self.assertEqual(made.chart["scenario"], "Call vs shove")
        self.assertEqual(made.chart["villain"], "BTN/SB")

    def test_a_seat_missing_at_that_table_size_is_not_solved(self):
        self.assertIsNone(pushfold_chart.solved(request(hero="UTG", players=2)))


class HistoryTests(unittest.TestCase):
    names = ("UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB")

    def test_first_in_means_everyone_before_folded(self):
        self.assertEqual(pushfold_chart.history(self.names, "CO", None), (0, 0, 0, 0))

    def test_facing_a_shove_marks_the_shover(self):
        self.assertEqual(pushfold_chart.history(self.names, "BB", "BTN"), (0, 0, 0, 0, 0, 1, 0))

    def test_every_shover_before_the_hero_is_marked(self):
        self.assertEqual(pushfold_chart.history(self.names, "SB", "UTG", ("UTG", "BTN")),
                         (1, 0, 0, 0, 0, 1))

    def test_a_villain_behind_the_hero_is_ignored(self):
        self.assertEqual(pushfold_chart.history(self.names, "SB", "BB"), (0,) * 6)

    def test_the_big_blind_alone_defends_against_the_small_blind(self):
        self.assertEqual(pushfold_chart.history(self.names, "BB", None), (0,) * 6 + (1,))


class SolvedChartTests(unittest.TestCase):
    def test_first_in_chart_shoves_aces_and_folds_trash(self):
        made = pushfold_chart.solved(request(hero="UTG", stack=10))
        codes = dict(zip(made.book["hand_order"], made.chart["actions"]))
        self.assertEqual(codes["AA"], "R")
        self.assertEqual(codes["72o"], "F")
        self.assertEqual(made.chart["scenario"], "Push/Fold")

    def test_facing_a_shove_the_chart_calls(self):
        made = pushfold_chart.solved(request(hero="BB", villain="SB", stack=10))
        codes = dict(zip(made.book["hand_order"], made.chart["actions"]))
        self.assertEqual(codes["AA"], "C")
        self.assertEqual(made.chart["villain"], "SB")
        self.assertEqual(made.chart["scenario"], "Call vs shove")

    def test_an_asked_hand_shows_shove_and_fold_percentages(self):
        made = pushfold_chart.solved(request(hero="SB", stack=12))
        hand = next(iter(made.chart["mixed"]))
        line = preflop.hand_answers(made.book, made.chart, [hand])[0]
        self.assertRegex(line, rf"^{hand} = (shove|fold) \d+% / (shove|fold) \d+%$")
        self.assertEqual(preflop.hand_answers(made.book, made.chart, ["AA"]), ["AA = shove 100%"])

    def test_mixed_cells_carry_their_frequencies(self):
        made = pushfold_chart.solved(request(hero="SB", stack=12))
        for hand, shares in made.chart["mixed"].items():
            self.assertAlmostEqual(sum(shares.values()), 1.0, places=6, msg=hand)

    def test_the_note_states_every_assumption(self):
        made = pushfold_chart.solved(request(stack=10))
        self.assertIn("8-handed", made.note)
        self.assertIn("10bb", made.note)
        self.assertIn("ante", made.note)
        self.assertIn("after the ante", made.note)


class PayoutWordsTests(unittest.TestCase):
    def test_payouts_are_read_in_english_and_thai(self):
        for said in ("BTN shove 10bb icm 50/30/20", "payout 50 30 20 BTN 10bb",
                     "BTN 10bb รางวัล 50/30/20", "BTN 10bb ICM 50%/30%/20%",
                     "prizes 50, 30, 20 BTN 10bb", "BTN 10bb ไอซีเอ็ม 50-30-20"):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).payouts, (50, 30, 20))

    def test_payout_numbers_are_not_read_as_the_stack_or_table(self):
        made = preflop.parse("icm 50/30/20 4 handed BTN 10bb")
        self.assertEqual((made.payouts, made.players, made.stack), ((50, 30, 20), 4, 10))
        made = preflop.parse("payout 50 30 20 10bb BTN")
        self.assertEqual((made.payouts, made.stack), ((50, 30, 20), 10))
        self.assertIsNone(preflop.parse("icm 50/30/20 BTN").stack)

    def test_icm_alone_means_the_default_payouts(self):
        for said in ("BTN shove 10bb icm", "BTN 10bb ไอซีเอ็ม"):
            with self.subTest(said=said):
                made = preflop.parse(said)
                self.assertTrue(made.icm)
                self.assertIsNone(made.payouts)
        note = pushfold_chart.solved(request(stack=10, icm=True)).note
        self.assertIn("bubble: 6 of 20 left", note)
        self.assertIn("5 paid, live payouts (500 THB buy-in: 3,880/2,590/1,660/1,110/760 THB)", note)

    def test_chip_ev_is_said_explicitly_or_left_out(self):
        self.assertEqual(preflop.parse("BTN 10bb chip ev").payouts, ())
        self.assertIsNone(preflop.parse("BTN 10bb").payouts)

    def test_cev_is_short_for_chip_ev(self):
        for said in ("Cev 10bb btn", "BTN 10bb cEV", "BTN 10bb c-ev"):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).payouts, ())
        self.assertIsNone(preflop.parse("BTN 10bb ICM").payouts)

    def test_saying_icm_after_chip_ev_switches_back_to_icm(self):
        import spot
        switched = spot.merge(preflop.parse("Icm"), preflop.Request(stack=10, hero="BTN", payouts=()))
        self.assertIsNone(switched.payouts)
        self.assertTrue(switched.icm)
        self.assertIn("ICM", pushfold_chart.solved(dataclasses.replace(switched, game="tournament")).note)

    def test_saying_icm_keeps_real_payouts_from_before(self):
        import spot
        kept = spot.merge(preflop.parse("icm"), preflop.Request(stack=10, payouts=(60, 40)))
        self.assertEqual(kept.payouts, (60, 40))

    def test_a_follow_up_keeps_the_payouts_until_chip_ev_is_asked(self):
        import spot
        kept = spot.merge(preflop.Request(stack=8), preflop.Request(hero="BTN", payouts=(50, 30, 20)))
        self.assertEqual(kept.payouts, (50, 30, 20))
        dropped = spot.merge(preflop.Request(payouts=()), preflop.Request(payouts=(50, 30, 20)))
        self.assertEqual(dropped.payouts, ())


class StageWordsTests(unittest.TestCase):
    def test_share_of_the_field_left_is_read(self):
        for said in ("BTN shove 10bb 50% left", "BTN 10bb 50% of the field left",
                     "BTN 10bb เหลือ 50%", "BTN 10bb เหลือ 50 เปอร์เซ็นต์"):
            with self.subTest(said=said):
                made = preflop.parse(said)
                self.assertEqual((made.left_pct, made.stack), (50, 10))

    def test_a_share_of_the_field_without_left_is_read(self):
        for said in ("SB vs UTG shove 13bb 80% field", "SB vs UTG shove 13bb 80% of field",
                     "SB vs UTG shove 13bb field 80%", "SB vs UTG shove 13bb 80 เปอร์เซ็นต์ field"):
            with self.subTest(said=said):
                made = preflop.parse(said)
                self.assertEqual((made.left_pct, made.entrants, made.stack), (80, None, 13))

    def test_field_with_a_plain_number_is_still_the_field_size(self):
        made = preflop.parse("BTN 10bb 50% left field 800")
        self.assertEqual((made.left_pct, made.entrants), (50, 800))

    def test_players_left_is_read_without_touching_the_table_size(self):
        made = preflop.parse("BTN 10bb 120 left 6-max")
        self.assertEqual((made.players_left, made.players), (120, 6))
        made = preflop.parse("BTN 10bb เหลือ 120 คน")
        self.assertEqual((made.players_left, made.players), (120, None))

    def test_field_size_paid_share_and_average_stack_are_read(self):
        made = preflop.parse("BTN shove 10bb 20% left field 500 paid 12% avg 25bb")
        self.assertEqual((made.entrants, made.paid_pct, made.field_avg, made.stack, made.left_pct),
                         (500, 12, 25, 10, 20))
        made = preflop.parse("BTN 10bb 300 entrants 15% paid สแตกเฉลี่ย 30bb เหลือ 20%")
        self.assertEqual((made.entrants, made.paid_pct, made.field_avg, made.stack), (300, 15, 30, 10))

    def test_zero_is_not_read_as_a_stage(self):
        made = preflop.parse("BTN 10bb 0 left field 0 paid 0%")
        self.assertEqual((made.players_left, made.entrants, made.paid_pct), (None, None, None))
        self.assertIsNone(pushfold_chart.payout_problem(request(stack=10, players_left=None)))

    def test_average_is_read_before_or_after_the_number(self):
        for said in ("BTN 10bb 50% left avg 25bb", "BTN 10bb 50% left 25bb average",
                     "BTN 10bb 50% left average stack 25bb"):
            with self.subTest(said=said):
                made = preflop.parse(said)
                self.assertEqual((made.field_avg, made.stack), (25, 10))

    def test_a_follow_up_keeps_the_stage_and_a_new_one_replaces_it(self):
        import spot
        kept = spot.merge(preflop.Request(stack=8), preflop.Request(left_pct=50, entrants=500))
        self.assertEqual((kept.left_pct, kept.entrants), (50, 500))
        moved = spot.merge(preflop.Request(players_left=40), preflop.Request(left_pct=50))
        self.assertEqual((moved.players_left, moved.left_pct), (40, None))


class NamedStageTests(unittest.TestCase):
    def test_bubble_and_final_table_words_are_read(self):
        for said, word in (("bubble BTN 10bb", "bubble"), ("BTN 10bb บับเบิล", "bubble"),
                           ("final table BTN 10bb", "final"), ("BTN 10bb FT", "final"),
                           ("BTN 10bb ไฟนอลเทเบิ้ล", "final"), ("BTN 10bb โต๊ะสุดท้าย", "final")):
            with self.subTest(said=said):
                self.assertEqual(preflop.parse(said).stage_word, word)

    def test_the_bubble_is_just_above_the_places_paid(self):
        made = pushfold_chart.solved(request(stack=10, stage_word="bubble"))
        self.assertIn("bubble: 6 of 20 left", made.note)
        self.assertIn("5 paid, live payouts", made.note)
        made = pushfold_chart.solved(request(stack=10, stage_word="bubble", entrants=1000))
        self.assertIn("bubble: 155 of 1000 left", made.note)
        self.assertIn("150 paid", made.note)
        self.assertIn("standard MTT payouts", made.note)

    def test_a_paid_share_leaves_the_live_table(self):
        made = pushfold_chart.solved(request(stack=10, stage_word="bubble", paid_pct=30))
        self.assertIn("6 paid, standard MTT payouts", made.note)

    def test_more_left_than_a_live_game_assumes_a_big_field(self):
        chosen = pushfold_chart.stage(request(stack=10, players_left=120))
        self.assertEqual((chosen.entrants, chosen.curve), (1000, "mtt"))

    def test_a_sit_and_go_bubble_shrinks_the_table(self):
        chosen = pushfold_chart.payouts(request(stack=10, stage_word="bubble", payouts=(50, 30, 20)))
        self.assertEqual((len(chosen.prizes), chosen.crowd), (3, 0))
        made = pushfold_chart.solved(request(hero="BB", villain="SB", stack=10, stage_word="bubble",
                                             payouts=(50, 30, 20)))
        self.assertIn("4-handed", made.note)
        self.assertIn("bubble: 4 left, 3 paid", made.note)

    def test_the_final_table_is_everyone_left(self):
        chosen = pushfold_chart.payouts(request(stack=10, stage_word="final", players=9))
        self.assertEqual((len(chosen.prizes), chosen.crowd), (5, 0))
        made = pushfold_chart.solved(request(stack=10, stage_word="final", players=9))
        self.assertIn("final table: 9 of 20 left", made.note)
        self.assertNotIn("others at", made.note)

    def test_numbers_beat_the_named_stage(self):
        chosen = pushfold_chart.payouts(request(stack=10, stage_word="bubble", players_left=300))
        self.assertEqual(chosen.crowd, 292)

    def test_a_named_stage_replaces_an_earlier_share_left(self):
        import spot
        moved = spot.merge(preflop.Request(stage_word="bubble"), preflop.Request(left_pct=50))
        self.assertEqual((moved.stage_word, moved.left_pct), ("bubble", None))
        back = spot.merge(preflop.Request(left_pct=40), preflop.Request(stage_word="final"))
        self.assertEqual((back.stage_word, back.left_pct), (None, 40))


class StageChartTests(unittest.TestCase):
    def test_half_the_field_left_is_solved_with_a_crowd(self):
        made = pushfold_chart.solved(request(stack=10, left_pct=50, entrants=1000))
        self.assertIn("500 of 1000 left (50%)", made.note)
        self.assertIn("150 paid", made.note)
        self.assertIn("others at 10bb", made.note)
        self.assertIn("ICM", made.book["title"])

    def test_half_the_field_left_is_close_to_chip_ev_but_the_bubble_is_not(self):
        seat = dict(hero="BB", villain="SB", stack=10)
        chip = pushfold_chart.solved(request(**seat)).chart["actions"].count("C")
        early = pushfold_chart.solved(request(**seat, left_pct=50, entrants=1000)).chart["actions"].count("C")
        bubble = pushfold_chart.solved(request(**seat, players_left=155, entrants=1000)).chart["actions"].count("C")
        self.assertLessEqual(abs(chip - early), chip * 0.15)
        self.assertLess(bubble, chip * 0.8)

    def test_real_payouts_replace_the_standard_curve(self):
        made = pushfold_chart.solved(request(stack=10, players_left=12, entrants=100, players=6,
                                             payouts=(30, 20, 14, 10, 8, 6, 5, 4, 3)))
        self.assertIn("12 of 100 left", made.note)
        self.assertIn("9 paid", made.note)
        self.assertNotIn("standard", made.note)

    def test_a_bb_ante_stage_gives_others_no_ante(self):
        chosen = pushfold_chart.payouts(request(stack=10, left_pct=50, ante_mode="bb"))
        self.assertEqual(chosen.crowd_stack, 10)
        chosen = pushfold_chart.payouts(request(stack=10, left_pct=50, ante=0.2))
        self.assertEqual(chosen.crowd_stack, 10.2)

    def test_chip_ev_wins_over_a_stage(self):
        made = pushfold_chart.solved(request(stack=10, left_pct=50, payouts=()))
        self.assertIn("chip EV", made.note)

    def test_fewer_left_than_seated_is_explained(self):
        self.assertIn("only 5 players left but 8 seated",
                      pushfold_chart.payout_problem(request(players_left=5, players=8)))

    def test_an_unstated_table_shrinks_to_the_players_left(self):
        self.assertIsNone(pushfold_chart.payout_problem(request(players_left=5)))
        self.assertEqual(len(pushfold_chart.table(request(players_left=5)).stacks), 5)


class IcmChartTests(unittest.TestCase):
    def test_the_note_and_title_say_icm_and_the_payouts(self):
        made = pushfold_chart.solved(request(stack=10, players=4, payouts=(50, 30, 20)))
        self.assertIn("ICM 50/30/20", made.note)
        self.assertIn("ICM", made.book["title"])
        self.assertIn("chip EV", pushfold_chart.solved(request(stack=10)).note)

    def test_the_bubble_calls_tighter_than_chip_ev(self):
        spot_ = dict(hero="BB", villain="SB", stack=10, players=4)
        chip = pushfold_chart.solved(request(**spot_)).chart["actions"].count("C")
        prize = pushfold_chart.solved(request(**spot_, payouts=(50, 30, 20))).chart["actions"].count("C")
        self.assertLess(prize, chip / 2)

    def test_more_places_paid_than_players_is_caught(self):
        self.assertIn("3 places paid but only 2",
                      pushfold_chart.payout_problem(request(players=2, payouts=(50, 30, 20))))
        self.assertIsNone(pushfold_chart.payout_problem(request(players=3, payouts=(50, 30, 20))))
        self.assertIsNone(pushfold_chart.solved(request(players=2, payouts=(50, 30, 20))))


class AnswerTests(SpotTestCase):
    def setUp(self):
        self.use_books(book([chart(hero="BTN", stack=30, raises=("AKo",))], game="tournament"))

    def test_make_chart_shows_the_solved_chart_for_short_stacks(self):
        text, found = spot_chart.answer("BTN shove 10bb tournament A2o", color=False)
        self.assertIn("Push/Fold", text)
        self.assertIn("push/fold Nash", text)
        self.assertEqual(found.chart["scenario"], "Push/Fold")
        self.assertEqual(found.request.stack, 10)

    def test_reply_gives_the_chart_and_its_note_without_drawing(self):
        made = spot_chart.reply("BTN shove 10bb tournament")
        self.assertIsNone(made.message)
        self.assertEqual(made.found.chart["scenario"], "Push/Fold")
        self.assertIn("push/fold Nash", made.note)

    def test_reply_explains_when_there_is_no_chart(self):
        made = spot_chart.reply("BTN open 30bb tournament")
        self.assertEqual(made.message, spot_chart.PUSH_FOLD_ONLY["EN"])
        self.assertEqual(made.kind, "push_fold_only")

    def test_reply_names_every_kind_of_answer(self):
        self.assertEqual(spot_chart.reply("BTN shove 10bb tournament").kind, "chart")
        self.assertEqual(spot_chart.reply("ICM คืออะไร").kind, "not_found")
        self.use_books(book([chart(hero="BB", stack=30)], game="tournament"))
        self.assertEqual(spot_chart.reply("BB 0.8bb push fold tournament").kind, "all_in_by_posting")

    def test_a_seat_not_at_the_table_is_told_which_seats_exist(self):
        self.use_books(book([chart(hero="UTG", stack=30)], game="tournament"))
        made = spot_chart.reply("utg 5bb โต๊ะ 4 คน")
        self.assertEqual(made.kind, "seat_not_at_table")
        self.assertIn("UTG", made.message)
        self.assertIn("CO, BTN, SB, BB", made.message)

    def test_more_places_paid_than_players_is_told_so(self):
        made = spot_chart.reply("heads-up BTN shove 10bb icm 50/30/20")
        self.assertEqual(made.kind, "bad_payouts")
        self.assertIn("3", made.message)
        self.assertIn("2", made.message)

    def test_an_icm_question_gets_an_icm_chart(self):
        made = spot_chart.reply("4 handed BTN shove 10bb icm 50/30/20")
        self.assertEqual(made.kind, "chart")
        self.assertIn("ICM 50/30/20", made.note)

    def test_deeper_stacks_say_only_push_fold_is_available(self):
        text, found = spot_chart.answer("BTN open 30bb tournament", color=False)
        self.assertEqual(text, spot_chart.PUSH_FOLD_ONLY["EN"])
        self.assertEqual(found.request.stack, 30)

    def test_a_follow_up_stack_then_gets_the_chart(self):
        _, found = spot_chart.answer("BTN open 30bb tournament", color=False)
        text, _ = spot_chart.answer("10bb", color=False,
                                    memory=found.request)
        self.assertIn("push/fold Nash", text)

    def test_a_hero_all_in_by_posting_is_told_so(self):
        self.use_books(book([chart(hero="BB", stack=30)], game="tournament"))
        text, _ = spot_chart.answer("BB 0.8bb push fold tournament", color=False)
        self.assertEqual(text, spot_chart.ALL_IN_BY_POSTING["EN"])


if __name__ == "__main__":
    unittest.main()


class AllInOrFoldTests(unittest.TestCase):
    """GGPoker All-in or Fold Hold'em $0.05/$0.10: 4-max, 10bb, no ante, 0.2bb showdown fee."""

    def test_parser_reads_every_way_of_saying_it(self):
        for said in ("aof BTN 10bb", "BTN all-in or fold", "all in or fold เราอยู่ BTN",
                     "ออลอินหรือโฟลด์ BTN", "AoF: BB vs CO"):
            self.assertTrue(preflop.parse(said).aof, said)
        self.assertFalse(preflop.parse("BTN all-in 10bb").aof)
        self.assertFalse(preflop.parse("chaofan BTN 10bb").aof)

    def test_all_in_does_not_become_a_shover(self):
        said = preflop.parse("aof BB vs CO")
        self.assertEqual((said.hero, said.villain), ("BB", "CO"))

    def test_routes_to_the_solver_without_a_stack(self):
        self.assertTrue(pushfold_chart.applies(preflop.Request(hero="BTN", aof=True)))
        self.assertTrue(pushfold_chart.applies(preflop.Request(game="cash", hero="BTN", aof=True)))

    def test_defaults_are_the_lowest_stake_table(self):
        table = pushfold_chart.table(preflop.Request(hero="BTN", aof=True))
        self.assertEqual(table.stacks, (10.0,) * 4)
        self.assertEqual((table.ante, table.fee), (0.0, pushfold_chart.AOF_FEE))
        self.assertAlmostEqual(pushfold_chart.AOF_FEE, 0.2)

    def test_said_values_win_over_the_defaults(self):
        table = pushfold_chart.table(preflop.Request(hero="BTN", aof=True, players=3, stack=8))
        self.assertEqual(table.stacks, (8.0,) * 3)

    def test_chart_names_the_game_and_the_fee(self):
        made = pushfold_chart.solved(preflop.Request(hero="BB", villain="CO", aof=True))
        self.assertEqual(made.book["game"], "cash")
        self.assertIn("All-in or Fold", made.book["title"])
        self.assertIn("0.2bb", made.note)
        self.assertIn("4-handed", made.note)
        self.assertEqual((made.chart["villain"], made.chart["stack"]), ("CO", 10))

    def test_utg_is_not_at_a_four_max_table(self):
        self.assertIsNotNone(pushfold_chart.missing_seat(preflop.Request(hero="UTG", aof=True)))

    def test_follow_up_keeps_the_game(self):
        first = spot_chart.reply("aof BTN")
        second = spot_chart.reply("BB vs BTN", memory=first.found.request)
        self.assertIn("All-in or Fold", second.found.book["title"])


class FacingSeveralTests(unittest.TestCase):
    """Every seat named after เจอ / vs is a shover; the asker is whoever is left."""

    def test_every_seat_after_facing_is_a_shover(self):
        for said in ("9 5 suited เจอ Cutoff เจอ Small blind", "aof 95s เจอ CO กับ SB",
                     "aof BB vs CO and SB", "aof BB เจอ CO แล้วก็ SB"):
            read = spot_chart.spot.read(said)
            self.assertEqual(set(read.shovers), {"CO", "SB"}, said)
            self.assertIn(read.hero, (None, "BB"), said)

    def test_one_seat_after_facing_is_unchanged(self):
        read = spot_chart.spot.read("aof BB vs CO")
        self.assertEqual((read.hero, read.villain, read.shovers), ("BB", "CO", ()))

    def test_facing_the_sb_leaves_only_the_bb(self):
        made = spot_chart.reply("aof 9 5 suited เจอ Cutoff เจอ Small blind")
        self.assertEqual(made.found.chart["hero"], "BB")
        self.assertEqual(made.found.chart["villain"], "CO+SB")
        self.assertEqual(made.found.chart["scenario"], pushfold_chart.FACING)

    def test_remembered_hero_that_is_now_a_shover_is_dropped(self):
        first = spot_chart.reply("aof CO")
        made = spot_chart.reply("95s เจอ Cutoff เจอ Small blind", memory=first.found.request)
        self.assertEqual((made.found.chart["hero"], made.found.chart["villain"]), ("BB", "CO+SB"))

    def test_remembered_hero_after_the_shovers_is_kept(self):
        first = spot_chart.reply("aof BTN")
        made = spot_chart.reply("เจอ CO เจอ SB", memory=first.found.request)
        self.assertEqual(made.found.chart["hero"], "BB")
        made = spot_chart.reply("aof SB vs CO and BTN")
        self.assertEqual((made.found.chart["hero"], made.found.chart["villain"]), ("SB", "CO+BTN"))
