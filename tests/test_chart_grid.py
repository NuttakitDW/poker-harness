"""Checks the 13x13 preflop grid drawn in the terminal."""

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "tests"))
import chart_grid  # noqa: E402
import preflop  # noqa: E402
from test_preflop import book, chart  # noqa: E402

ANSI = re.compile(r"\033\[[0-9;]*m")


def plain_rows(made_book, made_chart):
    return chart_grid.rows(made_book, made_chart, color=False)


class GridTests(unittest.TestCase):
    def test_there_are_thirteen_rows_of_thirteen_cells(self):
        made = book([chart(raises=("AA",))])
        lines = plain_rows(made, made["charts"][0])
        self.assertEqual(len(lines), 13)
        for line in lines:
            self.assertEqual(len(line[3:]), 13 * 4)

    def test_rows_are_labelled_by_the_high_card(self):
        made = book([chart()])
        labels = [line.split()[0] for line in plain_rows(made, made["charts"][0])]
        self.assertEqual("".join(labels), preflop.RANKS)

    def test_suited_hands_sit_above_the_diagonal(self):
        made = book([chart(raises=("AKs",))])
        first = plain_rows(made, made["charts"][0])[0]
        self.assertEqual(first[3:].split(), ["."] + ["R"] + ["."] * 11)

    def test_offsuit_hands_sit_below_the_diagonal(self):
        made = book([chart(calls=("AKo",))])
        second = plain_rows(made, made["charts"][0])[1]
        self.assertEqual(second[3:].split()[0], "C")

    def test_mixed_hands_are_marked_in_lower_case(self):
        made_chart = chart(raises=("AA",))
        made_chart["mixed"] = {"AA": {"raise": 0.6, "fold": 0.4}}
        made = book([made_chart])
        first = plain_rows(made, made_chart)[0]
        self.assertEqual(first[3:].split()[0], "r")

    def test_a_mixed_cell_takes_the_main_actions_colour(self):
        self.assertEqual(chart_grid.shade({"raise": 0.7, "fold": 0.3})[0], "R")
        self.assertEqual(chart_grid.shade({"raise": 0.3, "fold": 0.7})[0], "F")

    def test_the_less_often_played_the_lighter_the_shade(self):
        styles = [chart_grid.shade({"raise": p, "fold": 1 - p})[1] for p in (0.99, 0.9, 0.75, 0.55)]
        self.assertEqual(len(set(styles)), 4)
        self.assertEqual(styles[0], chart_grid.STYLES["R"])

    def test_a_coloured_mixed_cell_is_one_lighter_colour(self):
        made_chart = chart(raises=("AA",))
        made_chart["mixed"] = {"AA": {"raise": 0.7, "fold": 0.3}}
        line = chart_grid.rows(book([made_chart]), made_chart)[0]
        self.assertIn(chart_grid.shade({"raise": 0.7, "fold": 0.3})[1], line)
        self.assertNotIn(chart_grid.STYLES["F"], line.split("AA")[0])
        self.assertEqual(len(ANSI.sub("", line)[3:]), 13 * 4)

    def test_the_legend_explains_the_light_shade_of_every_colour(self):
        text = chart_grid.legend()
        for action in ("raise", "call", "fold"):
            with self.subTest(action=action):
                self.assertIn(chart_grid.shade({action: 0.6, "x": 0.4})[1], text)

    def test_an_asked_hand_gets_a_coloured_badge_per_action(self):
        made_chart = chart(raises=("AA",))
        made_chart["mixed"] = {"AA": {"raise": 0.7, "fold": 0.3}}
        text = chart_grid.render(book([made_chart]), made_chart, asked=("AA",))
        line = next(l for l in text.splitlines() if "70%" in l)
        self.assertIn(f"{chart_grid.STYLES['R']} raise 70% ", line)
        self.assertIn(f"{chart_grid.STYLES['F']} fold 30% ", line)
        self.assertEqual(text.splitlines()[text.splitlines().index(line) - 1], "")

    def test_coloured_cells_show_the_hand_name(self):
        made = book([chart(raises=("AKs",))])
        first = ANSI.sub("", chart_grid.rows(made, made["charts"][0])[0])
        self.assertIn("AKs", first)
        self.assertEqual(len(first[3:]), 13 * 4)

    def test_the_header_lines_up_with_the_cells(self):
        made = book([chart()])
        text = ANSI.sub("", chart_grid.render(made, made["charts"][0]))
        lines = text.splitlines()
        header, top = lines[2], lines[3]
        self.assertEqual(header.index("K"), top.index("AKs"))

    def test_render_names_the_situation_and_source_page(self):
        made = book([chart(hero="CO", page=9)])
        text = chart_grid.render(made, made["charts"][0], color=False)
        self.assertIn("CO", text.splitlines()[0])
        self.assertIn("หน้า 9", text)

    def test_mixed_frequencies_are_listed_under_the_grid(self):
        made_chart = chart()
        made_chart["mixed"] = {"77": {"raise": 0.5, "fold": 0.5}}
        text = chart_grid.render(book([made_chart]), made_chart, color=False)
        self.assertIn("เล่นผสม: 77", text)


class AskedHandTests(unittest.TestCase):
    def test_an_asked_hand_is_pointed_at_in_the_grid(self):
        made = book([chart(raises=("AKs",))])
        first = chart_grid.rows(made, made["charts"][0], color=False, asked=("AKs",))[0]
        self.assertEqual(first[3:].split()[1], ">R")

    def test_the_cells_keep_their_width_when_pointed_at(self):
        made = book([chart()])
        first = ANSI.sub("", chart_grid.rows(made, made["charts"][0], asked=("AKs",))[0])
        self.assertEqual(len(first[3:]), 13 * 4)
        self.assertIn(">AKs", first)

    def test_the_answer_for_the_asked_hand_is_printed_under_the_grid(self):
        made = book([chart(raises=("A9o",))])
        text = chart_grid.render(made, made["charts"][0], color=False, asked=("T8o",))
        self.assertIn("T8o = fold", text)


class LookupTests(unittest.TestCase):
    def setUp(self):
        original = preflop.books
        preflop.books = lambda: (book([chart(hero="UTG", stack=20)]),)
        self.addCleanup(lambda: setattr(preflop, "books", original))

    def test_a_matching_question_gets_a_grid(self):
        found = chart_grid.for_question("20BB อยู่ UTG เปิดอะไรได้", color=False)
        self.assertIsNotNone(found)
        self.assertIn("UTG", found[1])

    def test_the_same_chart_gives_the_same_key(self):
        first = chart_grid.for_question("20BB อยู่ UTG เปิดอะไรได้")
        again = chart_grid.for_question("UTG เปิดมือ 18BB")
        self.assertEqual(first[0], again[0])

    def test_asking_about_another_hand_redraws_the_same_chart(self):
        first = chart_grid.for_question("20BB อยู่ UTG เปิด AKo ได้ไหม")
        again = chart_grid.for_question("20BB อยู่ UTG เปิด 18 offsuit ได้ไหม")
        self.assertNotEqual(first[0], again[0])
        self.assertRegex(ANSI.sub("", again[1]), r"T8o\s+fold 100%")

    def test_an_unrelated_question_gets_nothing(self):
        self.assertIsNone(chart_grid.for_question("ICM คืออะไร"))


if __name__ == "__main__":
    unittest.main()
