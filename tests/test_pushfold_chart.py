"""Checks that short tournament stacks get a solved push/fold chart in make chart."""

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "tests"))
import preflop  # noqa: E402
import pushfold_chart  # noqa: E402
import spot_chart  # noqa: E402
from test_preflop import book, chart  # noqa: E402
from test_spot import SpotTestCase, agrees  # noqa: E402

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

    def test_a_stack_too_short_to_post_is_not_solved(self):
        self.assertIsNone(pushfold_chart.solved(request(hero="BB", stack=2)))


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

    def test_mixed_cells_carry_their_frequencies(self):
        made = pushfold_chart.solved(request(hero="SB", stack=12))
        for hand, shares in made.chart["mixed"].items():
            self.assertAlmostEqual(sum(shares.values()), 1.0, places=6, msg=hand)

    def test_the_note_states_every_assumption(self):
        made = pushfold_chart.solved(request(stack=10))
        self.assertIn("8-handed", made.note)
        self.assertIn("10bb", made.note)
        self.assertIn("ante", made.note)


class AnswerTests(SpotTestCase):
    def setUp(self):
        self.use_books(book([chart(hero="BTN", stack=30, raises=("AKo",))], game="tournament"))

    def test_make_chart_shows_the_solved_chart_for_short_stacks(self):
        text, found = spot_chart.answer("BTN shove 10bb tournament A2o", color=False,
                                        classify=agrees("BTN"))
        self.assertIn("Push/Fold", text)
        self.assertIn("push/fold Nash", text)
        self.assertEqual(found.chart["scenario"], "Push/Fold")
        self.assertEqual(found.request.stack, 10)

    def test_deeper_stacks_keep_the_book_chart(self):
        text, found = spot_chart.answer("BTN open 30bb tournament", color=False,
                                        classify=agrees("BTN"))
        self.assertNotIn("push/fold Nash", ANSI.sub("", text))
        self.assertEqual(found.chart["page"], 4)


if __name__ == "__main__":
    unittest.main()
