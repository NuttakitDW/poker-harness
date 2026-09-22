"""Checks for splitting streamed model output into speakable chunks."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import streaming  # noqa: E402


def drip(text: str, size: int = 5) -> list[str]:
    """จำลองการไหลของ token ทีละไม่กี่ตัวอักษร"""
    return [text[i:i + size] for i in range(0, len(text), size)]


class ChunkingTests(unittest.TestCase):
    def test_nothing_is_lost_or_duplicated(self):
        text = "ไม่มีตัวเลขตายตัวครับ SPR บอกว่ามือถูก commit ง่ายแค่ไหน " * 4
        joined = "".join(streaming.sentences(drip(text)))
        self.assertEqual(joined.replace(" ", ""), text.replace(" ", ""))

    def test_first_chunk_is_short_so_audio_starts_early(self):
        text = "ไม่มีตัวเลขตายตัวครับ " * 20
        chunks = list(streaming.sentences(drip(text)))
        self.assertLessEqual(len(chunks[0]), streaming.FIRST_MAX_CHARS)

    def test_later_chunks_may_be_longer_than_the_first(self):
        text = "ไม่มีตัวเลขตายตัวครับ " * 20
        chunks = list(streaming.sentences(drip(text)))
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(len(c) for c in chunks), streaming.MAX_CHARS)

    def test_english_sentence_boundaries_are_used(self):
        first = "The first sentence is long enough to stand alone."
        chunks = list(streaming.sentences(drip(f"{first} And here is the second one.")))
        self.assertEqual(chunks[0], first)

    def test_sentence_shorter_than_the_minimum_is_merged_forward(self):
        chunks = list(streaming.sentences(drip("Too short. But this tail makes it long enough to speak.")))
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("Too short."))

    def test_short_fragments_are_merged_not_emitted_alone(self):
        chunks = list(streaming.sentences(drip("ok. ยังไม่จบประโยคนี้นะครับ ต่ออีกหน่อย")))
        self.assertTrue(all(len(c) >= streaming.MIN_CHARS or c == chunks[-1] for c in chunks))

    def test_empty_stream_yields_nothing(self):
        self.assertEqual(list(streaming.sentences([])), [])

    def test_whitespace_only_stream_yields_nothing(self):
        self.assertEqual(list(streaming.sentences(["  ", "\n"])), [])
