"""Checks the chart-only spot lookup and its confidence score."""

from pathlib import Path
import re
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "tests"))
import preflop  # noqa: E402
import spot  # noqa: E402
import spot_chart  # noqa: E402
from test_preflop import book, chart  # noqa: E402

ANSI = re.compile(r"\033\[[0-9;]*m")


class SpotTestCase(unittest.TestCase):
    def use_books(self, *made):
        original = preflop.books
        preflop.books = lambda: made
        self.addCleanup(lambda: setattr(preflop, "books", original))


class LookupTests(SpotTestCase):
    def setUp(self):
        self.use_books(
            book([chart(hero="BB", villain="BTN", stack=30, page=33, calls=("K9o",)),
                  chart(hero="BB", villain="BTN", stack=50, page=34),
                  chart(hero="BTN", stack=30, page=8)]),
            book([chart(hero="UTG", stack=100, page=4, raises=("AKo",))], game="cash"),
        )

    def test_an_exact_match_is_fully_confident(self):
        found = spot.lookup("BB vs BTN open 30bb tournament")
        self.assertEqual(found.chart["page"], 33)
        self.assertEqual(found.confidence, 1.0)
        self.assertEqual(found.notes, ())

    def test_the_nearest_stack_is_used_and_costs_confidence(self):
        found = spot.lookup("BB vs BTN open 40bb tournament")
        self.assertIn(found.chart["stack"], (30, 50))
        self.assertLess(found.confidence, 1.0)
        self.assertTrue(any("40BB" in note for note in found.notes))

    def test_thai_questions_find_the_same_chart_with_thai_notes(self):
        found = spot.lookup("BB เจอ button เปิด 45bb ทัวร์")
        self.assertEqual(found.chart["page"], 34)
        self.assertEqual(found.lang, "TH")
        self.assertTrue(any("ถาม 45BB" in note for note in found.notes))

    def test_a_seat_the_rules_cannot_read_gives_nothing(self):
        # SystemOne used to guess BTN here; without it the asker must name a seat
        self.assertIsNone(spot.lookup("ตำแหน่งสุดท้าย chart 30bb tournament"))

    def test_nothing_is_found_without_any_seat(self):
        self.assertIsNone(spot.lookup("what is ICM"))

    def test_an_unstated_game_and_stack_are_noted(self):
        found = spot.lookup("UTG open AKo")
        self.assertEqual(found.book["game"], "cash")
        self.assertEqual(found.hands, ("AKo",))
        self.assertEqual(len(found.notes), 2)

    def test_the_confidence_line_shows_a_percentage(self):
        found = spot.lookup("BB vs BTN open 40bb tournament")
        self.assertRegex(spot.confidence_line(found), r"^confidence \d+%")


class MemoryTests(SpotTestCase):
    """The user's real voice session: follow-ups must keep the spot."""

    def setUp(self):
        self.use_books(
            book([chart(hero="BB", villain="BTN", stack=30, page=33),
                  chart(hero="BB", villain="UTG", stack=30, page=47),
                  chart(hero="BTN", villain="UTG", stack=30, page=20),
                  chart(hero="UTG", stack=30, page=3)]),
            book([chart(hero="BB", villain="BTN", stack=100, page=9),
                  chart(hero="BB", villain="UTG", stack=100, page=10),
                  chart(hero="BTN", villain="SB", scenario="3-Bet", stack=100, page=17)],
                 game="cash"),
        )

    def ask(self, *prompts):
        memory = None
        found = None
        for prompt in prompts:
            found = spot.lookup(prompt, memory=memory)
            memory = found.request if found else memory
        return found

    def test_big_blind_three_betting_the_button_is_bb_facing_the_open(self):
        found = self.ask("Hello เอ่อ ขอสปอต เอ่อ บิ๊กบาย 3-bet ใส่ button")
        self.assertEqual((found.chart["hero"], found.chart["villain"]), ("BB", "BTN"))

    def test_a_new_stack_keeps_the_seats(self):
        found = self.ask("บิ๊กบาย 3-bet ใส่ button", "ขอเปลี่ยนเป็น 25 บิ๊กบาย")
        self.assertEqual((found.chart["hero"], found.chart["villain"]), ("BB", "BTN"))
        self.assertEqual(found.chart["stack"], 30)
        self.assertIn("ต่อจากคำถามก่อน", found.notes)

    def test_a_correction_swaps_only_the_opponent(self):
        found = self.ask("BB เจอ UTG 25bb", "เจอ button ไม่ใช่เจอ UTG")
        self.assertEqual((found.chart["hero"], found.chart["villain"]), ("BB", "BTN"))
        self.assertEqual(found.chart["stack"], 30)

    def test_a_new_hero_drops_the_old_opponent(self):
        found = self.ask("BB เจอ button 25bb", "UTG เปิดอะไรบ้าง")
        self.assertEqual((found.chart["hero"], found.chart.get("villain")), ("UTG", None))
        self.assertEqual(found.chart["stack"], 30)

    def test_an_off_topic_turn_keeps_the_memory(self):
        found = self.ask("BB เจอ button 25bb", "ฮัลโหล ได้ยินไหมครับ", "ขอ 100bb")
        self.assertEqual((found.chart["hero"], found.chart["stack"]), ("BB", 100))

    def test_a_remembered_game_gives_way_to_a_stack_it_does_not_have(self):
        found = self.ask("BB เจอ button 100bb cash game", "ขอ 30 big blind")
        self.assertEqual((found.book["game"], found.chart["stack"]), ("tournament", 30))
        self.assertEqual(found.confidence, round(spot.FROM_MEMORY * spot.GAME_SWITCH, 2))
        self.assertTrue(any("30BB" in note for note in found.notes))

    def test_a_game_said_in_the_same_turn_is_a_hard_filter(self):
        found = self.ask("BB เจอ button cash 30bb")
        self.assertEqual((found.book["game"], found.chart["stack"]), ("cash", 100))

    def test_the_remembered_game_still_wins_when_it_has_the_stack(self):
        found = self.ask("BB เจอ button 30bb tournament", "UTG เปิด", "BB เจอ button 100bb")
        self.assertEqual(found.book["game"], "cash")

    def test_an_open_chart_at_another_stack_beats_facing_an_open(self):
        self.use_books(book([chart(hero="SB", villain="UTG", stack=12, page=82),
                             chart(hero="SB", stack=20, page=40)]))
        found = self.ask("ขอ 10 Big blind ตำแหน่ง Small blind raise first in ทัวร์นาเมนต์")
        self.assertEqual((found.chart.get("villain"), found.chart["stack"]), (None, 20))

    def test_equal_gaps_either_side_pick_the_shorter_stack(self):
        self.assertEqual(spot.stack_gap(12, 16), spot.stack_gap(20, 16))
        self.use_books(book([chart(hero="SB", stack=12, page=40),
                             chart(hero="SB", stack=20, page=41)]))
        found = self.ask("SB open 16bb tournament")
        self.assertEqual(found.chart["stack"], 12)

    def test_calling_a_jam_picks_the_all_in_chart(self):
        self.use_books(book([chart(hero="SB", villain="UTG", scenario="All-In", stack=12, page=82),
                             chart(hero="SB", villain="UTG", stack=20, page=63)]))
        found = self.ask("ขอฉาด Push/fold 16 Big blind Call open jam จากตําแหน่ง small blind "
                         "คน jam เป็น UTG")
        self.assertEqual((found.chart["scenario"], found.chart["stack"]), ("All-In", 12))

    def test_small_talk_does_not_redraw_the_remembered_chart(self):
        first = self.ask("BB เจอ button 25bb")
        self.assertIsNone(spot.lookup("ฮัลโหล ได้ยินไหมครับ",
                                      memory=first.request))

    def test_without_memory_a_lone_opponent_is_not_the_hero(self):
        self.assertIsNone(spot.lookup("เจอ button ไม่ใช่เจอ UTG"))


class LanguageTests(unittest.TestCase):
    def test_thai_letters_mean_thai(self):
        self.assertEqual(spot.language_of("BB เจอ BTN"), "TH")

    def test_plain_latin_means_english(self):
        self.assertEqual(spot.language_of("BB vs BTN"), "EN")


class AnswerTests(SpotTestCase):
    def setUp(self):
        made = chart(hero="UTG", stack=100, raises=("AKo",))
        made["mixed"] = {"77": {"raise": 0.5, "fold": 0.5}}
        self.use_books(book([made], game="cash"))

    def test_a_cash_spot_says_only_push_fold_is_available(self):
        text, found = spot_chart.answer("UTG open AKo 100bb cash", color=False)
        self.assertEqual(text, spot_chart.PUSH_FOLD_ONLY["EN"])
        self.assertEqual(found.request.hero, "UTG")

    def test_the_push_fold_only_reply_follows_the_asked_language(self):
        text, _ = spot_chart.answer("UTG เปิด 100bb cash", color=False)
        self.assertEqual(text, spot_chart.PUSH_FOLD_ONLY["TH"])

    def test_a_missing_spot_says_so_in_the_asked_language(self):
        text, found = spot_chart.answer("ICM คืออะไร", color=False)
        self.assertIsNone(found)
        self.assertEqual(text, spot_chart.MISSING["TH"])


class HelpTests(unittest.TestCase):
    def test_help_is_thai_by_default_and_english_on_request(self):
        self.assertIn("ถามตำแหน่งกับสแตก", spot_chart.help_for("/help"))
        self.assertIn("Name a seat", spot_chart.help_for("/help en"))
        self.assertEqual(spot_chart.help_for("/h"), spot_chart.help_for("/help th"))
        self.assertEqual(spot_chart.help_for("/?"), spot_chart.help_for("/help"))

    def test_other_text_is_not_a_help_command(self):
        self.assertIsNone(spot_chart.help_for("BTN shove 10bb"))
        self.assertIsNone(spot_chart.help_for("/hello"))

    def test_both_languages_list_every_command(self):
        for lang in ("th", "en"):
            text = spot_chart.help_for(f"/help {lang}")
            for command in ("/v, /voice", "/t, /text", "/n, /new", "/q, /quit", "/h, /help",
                            "Usage", "make chart"):
                with self.subTest(lang=lang, command=command):
                    self.assertIn(command, text)




if __name__ == "__main__":
    unittest.main()
