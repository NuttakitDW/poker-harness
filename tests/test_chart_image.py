"""Checks the PNG chart that the Discord bot sends."""

from io import BytesIO
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "tests"))
import chart_grid  # noqa: E402
import chart_image  # noqa: E402
from test_preflop import book, chart  # noqa: E402


class ChartImageTests(unittest.TestCase):
    def setUp(self):
        made = chart(hero="BTN", raises=("AA",), calls=("KK",))
        made["mixed"] = {"AKs": {"raise": 0.6, "fold": 0.4}}
        self.book, self.chart = book([made]), made

    def draw(self, **kwargs) -> Image.Image:
        data = chart_image.render(self.book, self.chart, **kwargs)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        return Image.open(BytesIO(data)).convert("RGB")

    def test_cells_are_painted_with_the_terminal_colours(self):
        picture = self.draw()
        for (row, col), (code, shares) in {(0, 0): ("R", None), (1, 1): ("C", None),
                                            (0, 1): ("R", {"raise": 0.6, "fold": 0.4}),
                                            (5, 5): ("F", None)}.items():
            with self.subTest(cell=(row, col)):
                x, y = chart_image.cell_origin(row, col)
                expected = chart_image.rgb(chart_grid.tone(code, shares)[1])
                self.assertEqual(picture.getpixel((x + 2, y + 2)), expected)

    def test_asked_hands_and_notes_make_the_picture_taller(self):
        plain = self.draw()
        longer = self.draw(asked=("AKs",), notes=("push/fold Nash, 8-handed",))
        self.assertGreater(longer.height, plain.height)
        self.assertEqual(longer.width, plain.width)

    def test_the_legend_paints_a_swatch_for_every_action_in_the_chart(self):
        picture = self.draw(lang="EN")
        entries = chart_grid.legend_entries(self.chart, "EN")
        self.assertEqual([code for code, _ in entries], ["R", "C", "F"])
        for index, (code, _) in enumerate(entries):
            with self.subTest(code=code):
                x, y = chart_image.legend_swatch(entries, index)
                expected = chart_image.rgb(chart_grid.tone(code, None)[1])
                self.assertEqual(picture.getpixel((x + 2, y + 2)), expected)

    def test_the_xterm_palette_is_converted_to_rgb(self):
        self.assertEqual(chart_image.rgb(16), (0, 0, 0))
        self.assertEqual(chart_image.rgb(231), (255, 255, 255))
        self.assertEqual(chart_image.rgb(124), (175, 0, 0))


class FontPathTests(unittest.TestCase):
    def test_defaults_to_the_macos_font(self):
        self.assertEqual(chart_image.font_path({}), chart_image.FONT_PATH)

    def test_chart_font_overrides_it_on_linux_hosts(self):
        self.assertEqual(chart_image.font_path({"CHART_FONT": "/fonts/x.ttf"}), "/fonts/x.ttf")


if __name__ == "__main__":
    unittest.main()
