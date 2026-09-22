import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.build_source_corpus import crc32, extract_archive, low_text_ocr_note, safe_archive_member, text_fence
from scripts.validate_harness import headings, native_text_present, prose_only, source_page_sections, validate_curated


class ArchiveSafetyTests(unittest.TestCase):
    def test_rejects_traversal_and_unexpected_files(self):
        for name in (
            "../outside.pdf",
            "Poker book/../outside.pdf",
            "/Poker book/outside.pdf",
            "Poker book/note.txt",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_archive_member(name)

    def test_preserves_utf8_archive_path(self):
        path = safe_archive_member("Poker book/915850_เอกสาร 1 (3).pdf")
        self.assertEqual(path.name, "915850_เอกสาร 1 (3).pdf")

    def test_crc_changes_when_content_changes_at_same_size(self):
        with tempfile.TemporaryDirectory() as work:
            file = Path(work) / "source.pdf"
            file.write_bytes(b"abcd")
            original = crc32(file)
            file.write_bytes(b"abce")
            self.assertNotEqual(original, crc32(file))

    def test_rerun_rejects_changed_pdf_with_same_size(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            archive = root / "books.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr("Poker book/book.pdf", b"good")
            with patch("scripts.build_source_corpus.SOURCE_ROOT", root / "sources"):
                extracted = extract_archive(archive)
                self.assertEqual(extracted[0].read_bytes(), b"good")
                extracted[0].write_bytes(b"evil")
                with self.assertRaisesRegex(ValueError, "CRC or size"):
                    extract_archive(archive)


class MarkdownParsingTests(unittest.TestCase):
    def test_ignores_fake_headings_and_links_inside_source_text(self):
        body = "## PDF page 1\n\n```text\n## PDF page 999\n[bad](missing.md)\n```\n"
        self.assertEqual(headings(body), {"pdf-page-1"})
        self.assertNotIn("missing.md", prose_only(body))

    def test_page_sections_ignore_fake_heading_inside_extracted_text(self):
        body = "## PDF page 1\n\n```text\n## PDF page 999\nbody\n```\n\n## PDF page 2\n\n[No extractable PDF text on this page.]\n"
        sections = source_page_sections(body)
        self.assertEqual(set(sections), {1, 2})
        self.assertIn("## PDF page 999", sections[1])
        self.assertNotIn("PDF page 2", sections[1])

    def test_long_source_fence_does_not_expose_embedded_headings_or_links(self):
        content = "before\n`````\n## PDF page 999\n[bad](missing.md)\n`````\nafter"
        fence = text_fence(content)
        self.assertEqual(fence, "``````")
        body = f"## PDF page 1\n{fence}text\n{content}\n{fence}\n## PDF page 2\n"
        visible = prose_only(body)
        self.assertNotIn("PDF page 999", visible)
        self.assertNotIn("missing.md", visible)
        self.assertEqual(set(source_page_sections(body)), {1, 2})

    def test_native_text_requires_closed_nonempty_block_before_ocr(self):
        ocr = "### OCR supplement (unverified)\n\n```text\nOCR content\n```"
        self.assertFalse(native_text_present("```text\n\n```\n" + ocr))
        self.assertFalse(native_text_present(ocr))
        # Until the native fence closes, an OCR-looking heading is PDF text.
        self.assertTrue(native_text_present("```text\nPDF content\n" + ocr))
        self.assertTrue(native_text_present("````text\nPDF content\n```\nmore content\n````\n" + ocr))

    def test_native_text_keeps_literal_ocr_heading_inside_fence(self):
        body = "```text\n## PDF page 999\n### OCR supplement (unverified)\nPDF content\n```\n### OCR supplement (unverified)\n"
        self.assertTrue(native_text_present(body))
        document = "## PDF page 1\n\n" + body + "\n## PDF page 2\n\n```text\nSecond page\n```\n"
        self.assertEqual(set(source_page_sections(document)), {1, 2})


class CorpusIntegrityTests(unittest.TestCase):
    def test_ocr_note_reports_attempts_per_book(self):
        self.assertIn("OCR was attempted on pages 1, 4", low_text_ocr_note([1, 4, 5], [1, 4], "EN"))
        self.assertIn("ทดลอง OCR แล้วในหน้า: 1, 4", low_text_ocr_note([1, 4, 5], [1, 4], "TH"))
        self.assertIn("No OCR was attempted for this book", low_text_ocr_note([5], [], "EN"))

    def test_curated_validation_detects_missing_guide_and_empty_topic_source(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            topic = root / "harnesses" / "EN" / "topics" / "01-example.md"
            topic.parent.mkdir(parents=True)
            topic.write_text("# Example\n\n- Stable ID: `01-example`\n\n## Core idea\n\nExample\n\n## Worked example (authored; not quoted from source)\n\nExample\n\n## Source pages\n\n", encoding="utf-8")
            errors = validate_curated(root, [{"id": "book-one"}])
            self.assertTrue(any("EN guide coverage" in error and "book-one" in error for error in errors))
            self.assertTrue(any("Missing page-specific source citation" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
