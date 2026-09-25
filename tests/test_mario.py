"""Checks the mario easter egg: the river chart that answers any question containing mario."""

from io import BytesIO
from pathlib import Path
import re
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import mario  # noqa: E402
import spot_chart  # noqa: E402

ANSI = re.compile(r"\033\[[0-9;]*m")


class MarioTests(unittest.TestCase):
    def test_mario_anywhere_in_the_text_triggers_it(self):
        for text in ("mario", "MARIO", "show me Mario please", "super mario bros", "มาริโอ้ mario"):
            self.assertTrue(mario.asked(text), text)

    def test_ordinary_questions_do_not_trigger_it(self):
        for text in ("BTN shove 10bb", "marine", "mar io", ""):
            self.assertFalse(mario.asked(text), text)

    def test_every_one_of_the_169_hands_has_an_action_and_ev(self):
        self.assertEqual(len(mario.CELLS), 169)
        self.assertEqual(len({hand for hand, _, _ in mario.CELLS}), 169)
        self.assertTrue(all(code in mario.ACTIONS for _, code, _ in mario.CELLS))

    def test_the_grid_matches_the_screenshot_corners(self):
        cells = {hand: (code, ev) for hand, code, ev in mario.CELLS}
        self.assertEqual(cells["AA"], ("X", 17.8))
        self.assertEqual(cells["KJs"], ("A", 358.0))
        self.assertEqual(cells["54s"], ("A", -198.2))
        self.assertEqual(cells["22"], ("X", 22.1))

    def test_the_terminal_chart_names_the_board_and_every_action(self):
        shown = ANSI.sub("", mario.render(color=True))
        for word in ("6h 9d Td Qc 2s", "Check", "Bet 33", "Bet 66", "Allin 500", "KJs", "358.0"):
            self.assertIn(word, shown)

    def test_the_plain_chart_has_no_colour_codes(self):
        self.assertNotIn("\033[", mario.render(color=False))

    def test_the_png_is_a_real_image(self):
        picture = Image.open(BytesIO(mario.png()))
        self.assertEqual(picture.format, "PNG")
        self.assertGreater(picture.width, 600)

    def test_spot_chart_answers_mario_with_the_easter_egg(self):
        made = spot_chart.reply("hey mario")
        self.assertEqual(made.kind, "mario")
        self.assertIsNone(made.found)
        shown, found = spot_chart.answer("mario", color=False)
        self.assertIsNone(found)
        self.assertIn("Allin 500", shown)


if __name__ == "__main__":
    unittest.main()
