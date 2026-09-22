"""Checks for assembling streamed transcription tokens into finished sentences."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import soniox_rt  # noqa: E402


def message(*tokens: tuple[str, bool], finished: bool = False) -> dict:
    return {"tokens": [{"text": text, "is_final": final} for text, final in tokens],
            "finished": finished}


class AssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assembler = soniox_rt.Assembler()

    def test_nothing_closes_while_the_speaker_is_still_going(self):
        self.assertEqual(self.assembler.push(message(("เจอ ", True), ("c-bet", True))), [])

    def test_the_end_marker_closes_the_sentence(self):
        self.assembler.push(message(("เจอ ", True), ("c-bet", True)))
        self.assertEqual(self.assembler.push(message(("<end>", False))), ["เจอ c-bet"])

    def test_markers_never_reach_the_sentence(self):
        closed = self.assembler.push(message(
            ("range ", True), ("แคบ", True), ("<end>", False), ("<fin>", False)))
        self.assertEqual(closed, ["range แคบ"])

    def test_two_sentences_in_one_message_both_come_out(self):
        closed = self.assembler.push(message(
            ("หนึ่ง", True), ("<end>", False), ("สอง", True), ("<end>", False)))
        self.assertEqual(closed, ["หนึ่ง", "สอง"])

    def test_speaking_turns_on_with_words_and_off_at_the_boundary(self):
        self.assembler.push(message(("กำลังพูด", True)))
        self.assertTrue(self.assembler.speaking)
        self.assembler.push(message(("<end>", False)))
        self.assertFalse(self.assembler.speaking)

    def test_a_boundary_with_nothing_said_produces_no_sentence(self):
        self.assertEqual(self.assembler.push(message(("<end>", False))), [])

    def test_words_that_are_not_final_yet_are_not_kept(self):
        self.assembler.push(message(("เดา", False), ("แน่", True)))
        self.assertEqual(self.assembler.push(message(("<end>", False))), ["แน่"])

    def test_flush_returns_what_was_left_when_the_line_closes_early(self):
        self.assembler.push(message(("ค้างอยู่", True)))
        self.assertEqual(self.assembler.flush(), "ค้างอยู่")
        self.assertEqual(self.assembler.flush(), "")


class CleanTests(unittest.TestCase):
    def test_marker_only_text_becomes_empty(self):
        self.assertEqual(soniox_rt.clean("<end><fin>"), "")

    def test_spacing_around_removed_markers_is_tidied(self):
        self.assertEqual(soniox_rt.clean("เจอ <end> c-bet"), "เจอ c-bet")


class ChunkTests(unittest.TestCase):
    def test_audio_is_cut_into_even_pieces_with_a_short_tail(self):
        pieces = list(soniox_rt._chunks(b"x" * 25, 10))
        self.assertEqual([len(piece) for piece in pieces], [10, 10, 5])

    def test_empty_audio_produces_no_pieces(self):
        self.assertEqual(list(soniox_rt._chunks(b"", 10)), [])


class ConfigTests(unittest.TestCase):
    def test_the_glossary_travels_with_the_session(self):
        self.assertIn("Check-raise", soniox_rt._config("key")["context"]["terms"])

    def test_endpoint_detection_is_asked_for(self):
        self.assertTrue(soniox_rt._config("key")["enable_endpoint_detection"])

    def test_the_audio_format_matches_what_the_microphone_produces(self):
        config = soniox_rt._config("key")
        self.assertEqual(config["sample_rate"], soniox_rt.SAMPLE_RATE)
        self.assertEqual(config["num_channels"], 1)


if __name__ == "__main__":
    unittest.main()
