"""Checks for turning the PLO drill pages into short knowledge notes."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import build_plo_notes as plo  # noqa: E402
import brain  # noqa: E402

WEB = ROOT / "harnesses" / "EN" / "sources" / "web"


class HandTests(unittest.TestCase):
    def test_hand_shows_suits_ranks_and_shape(self):
        self.assertEqual(plo.hand("KsKdQdJs"), "K♠K♦Q♦J♠ (KKQJ double-suited)")
        self.assertEqual(plo.hand("AcAdTc6s"), "A♣A♦T♣6♠ (AAT6 single-suited)")
        self.assertEqual(plo.hand("9s7d5c3h"), "9♠7♦5♣3♥ (9753 rainbow)")

    def test_board_keeps_plain_cards(self):
        self.assertEqual(plo.hand("As4d3s"), "A♠4♦3♠")

    def test_th_strips_markup(self):
        self.assertEqual(plo.th({"en": "x", "th": "<b>Raise</b> &amp; call"}), "Raise & call")


class ChunkTests(unittest.TestCase):
    def test_chunk_respects_budget(self):
        groups = plo.chunk(["a" * 60, "b" * 60, "c" * 60], budget=130)
        self.assertEqual([len(g) for g in groups], [2, 1])

    def test_oversized_block_stays_alone(self):
        self.assertEqual(plo.chunk(["x" * 500, "y"], budget=100), [["x" * 500], ["y"]])


class NoteFileTests(unittest.TestCase):
    def test_notes_exist_for_every_page(self):
        for page in plo.PAGES:
            with self.subTest(page=page.slug):
                self.assertTrue(list(WEB.glob(f"{page.slug}-primer-*.md")))

    def test_notes_fit_prompt_budget(self):
        for path in WEB.glob(f"{plo.PREFIX}*.md"):
            with self.subTest(note=path.name):
                self.assertLessEqual(len(path.read_text(encoding="utf-8")), brain.MAX_PAGE_CHARS)


if __name__ == "__main__":
    unittest.main()
