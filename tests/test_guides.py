"""Regression checks for physical-page routes in the authored study guides."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_guides as guides  # noqa: E402


class GuideRouteTests(unittest.TestCase):
    def test_prose_cross_reference_is_not_chapter_start(self):
        pages = [(1, "Contents\nChapter 5 After the Flop"), (20, "In chapter 5 After the Flop we cover this"), (42, "After the Flop\nActual chapter text")]
        self.assertEqual(guides.locate(pages, "After the Flop", "pot-limit-omaha-jeff-hwang"), (42, True))

    def test_page_reader_excludes_metadata_and_unverified_ocr(self):
        pages = dict(guides.read_pages("super-system-2"))
        self.assertIn("SEVEN CARD STUD HIGH LOW EIGHT-OR-BETTER", pages[223])
        self.assertNotIn("[Open source PDF]", pages[223])
        self.assertNotIn("OCR supplement (unverified)", pages[223])

    def test_embedded_page_and_ocr_headings_remain_native_text(self):
        document = "## PDF page 1\n\n````text\n## PDF page 999\n### OCR supplement (unverified)\nNative text\n````\n\n### OCR supplement (unverified)\n\n```text\nUnverified OCR\n```\n\n## PDF page 2\n\n```text\nSecond page\n```\n"
        pages = dict(guides.parse_page_document(document))
        self.assertEqual(set(pages), {1, 2})
        self.assertIn("Native text", pages[1])
        self.assertNotIn("Unverified OCR", pages[1])
        self.assertIn("Second page", pages[2])

    def test_reviewed_routes_in_both_languages(self):
        for language in ("EN", "TH"):
            root = ROOT / "harnesses" / language / "guides"
            hwang = (root / "pot-limit-omaha-jeff-hwang.md").read_text()
            if language == "EN":
                self.assertIn("1. The Big Play Objectives](../../../sources/pdf/Pot_Limit_Omaha_Jeff_Hwang.pdf#page=24)", hwang)
            else:
                self.assertIn("#page=24", hwang)
            for page in (77, 106, 182, 201, 300):
                self.assertIn(f"#page={page})", hwang)
            super_system = (root / "super-system-2.md").read_text()
            self.assertIn("#page=223)", super_system)
            self.assertIn("#page=224)", super_system)
            thai = (root / "thai-document-915850.md").read_text()
            for page in (1, 2, 4, 5):
                self.assertIn(f"#page={page})", thai)
            self.assertNotIn("#page=22)\n- [5.", hwang)
            six_max = (root / "two-plus-two-nl-six-max.md").read_text()
            self.assertIn("#page=4)", six_max)


if __name__ == "__main__":
    unittest.main()
