"""Checks that thinking is separated from what actually gets spoken."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import brain  # noqa: E402
import journal  # noqa: E402
import streaming  # noqa: E402

MARKER = brain.SAY_MARKER


def split(pieces):
    return list(streaming.split_reasoning(iter(pieces), MARKER))


class SplitReasoningTests(unittest.TestCase):
    def test_thinking_and_speech_are_separated(self):
        result = split([f"คิด: สแตก 3 BB สั้นมาก\n{MARKER} shove ได้กว้างเลยค่ะ"])
        self.assertEqual(result[0][0], "think")
        self.assertIn("3 BB", result[0][1])
        self.assertEqual("".join(text for channel, text in result if channel == "say"),
                         "shove ได้กว้างเลยค่ะ")

    def test_a_marker_split_across_pieces_is_still_found(self):
        result = split(["คิด: สั้น ", "ตอ", "บ:", " shove เลย"])
        self.assertEqual([channel for channel, _ in result][0], "think")
        self.assertIn("shove เลย", "".join(t for c, t in result if c == "say"))

    def test_speech_keeps_streaming_piece_by_piece(self):
        result = split([f"คิด: x\n{MARKER} หนึ่ง", "สอง", "สาม"])
        said = [text for channel, text in result if channel == "say"]
        self.assertEqual(len(said), 3)

    def test_an_answer_without_a_marker_is_spoken_whole(self):
        result = split(["ตอบตรง ๆ เลยค่ะ ", "ไม่มีส่วนคิด"])
        self.assertEqual(result, [("say", "ตอบตรง ๆ เลยค่ะ ไม่มีส่วนคิด")])

    def test_nothing_from_the_model_says_nothing(self):
        self.assertEqual(split([""]), [])

    def test_a_marker_with_no_thinking_before_it_yields_only_speech(self):
        self.assertEqual(split([f"{MARKER} พูดเลย"]), [("say", "พูดเลย")])


class PromptTests(unittest.TestCase):
    def test_the_two_part_rule_is_sent_when_reasoning_is_on(self):
        system = brain.build_messages("ถาม", "บริบท")[0]["content"]
        self.assertIn(brain.THINK_MARKER, system)
        self.assertIn(brain.SAY_MARKER, system)
        self.assertIn("push/fold", system)

    def test_the_rule_is_left_out_when_reasoning_is_off(self):
        system = brain.build_messages("ถาม", "บริบท", reasoning=False)[0]["content"]
        self.assertNotIn(brain.SAY_MARKER, system)


class ShowingThinkingTests(unittest.TestCase):
    def test_thinking_is_shown_line_by_line(self):
        line = journal.describe("reasoning", {"text": "สแตก 3 BB\nตำแหน่ง UTG"})
        self.assertIn("คิด:", line)
        self.assertIn("สแตก 3 BB", line)
        self.assertIn("ตำแหน่ง UTG", line)

    def test_empty_thinking_still_prints_something(self):
        self.assertIn("คิด", journal.describe("reasoning", {"text": ""}))


if __name__ == "__main__":
    unittest.main()
