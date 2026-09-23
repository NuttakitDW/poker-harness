"""Checks the live wave that shows the speaker their voice is getting through."""

import io
from pathlib import Path
import sys
import unittest

import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import meter  # noqa: E402

ELLIPSIS = meter.ELLIPSIS


def tone(amplitude: float) -> "numpy.ndarray":
    return numpy.full(512, amplitude, dtype=numpy.float32)


class Screen(io.StringIO):
    def isatty(self) -> bool:
        return True


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class LevelTests(unittest.TestCase):
    def test_silence_is_zero(self):
        self.assertEqual(meter.level_of(tone(0.0)), 0.0)

    def test_an_empty_frame_is_zero(self):
        self.assertEqual(meter.level_of(numpy.zeros(0, dtype=numpy.float32)), 0.0)

    def test_full_scale_is_capped_at_one(self):
        self.assertEqual(meter.level_of(tone(1.0)), 1.0)

    def test_louder_speech_reads_higher(self):
        self.assertLess(meter.level_of(tone(0.01)), meter.level_of(tone(0.1)))

    def test_room_noise_stays_below_the_speaking_line(self):
        self.assertLess(meter.level_of(tone(0.001)), meter.ACTIVE_LEVEL)

    def test_normal_speech_crosses_the_speaking_line(self):
        self.assertGreater(meter.level_of(tone(0.05)), meter.ACTIVE_LEVEL)

    def test_bars_run_from_blank_to_full(self):
        self.assertEqual(meter.bar(0.0), " ")
        self.assertEqual(meter.bar(1.0), "█")
        self.assertEqual(meter.bar(7.0), "█")


class WidthTests(unittest.TestCase):
    def test_thai_marks_above_and_below_take_no_room(self):
        self.assertEqual(meter.display_width("ที่"), 1)
        self.assertEqual(meter.display_width("สวัสดี"), 4)

    def test_text_that_fits_is_left_alone(self):
        self.assertEqual(meter.tail_fit("สวัสดี", 10), "สวัสดี")

    def test_long_text_keeps_the_latest_words(self):
        fitted = meter.tail_fit("abcdefghij", 5)
        self.assertEqual(fitted, "…ghij")

    def test_trimming_never_leaves_a_mark_without_its_letter(self):
        self.assertEqual(meter.tail_fit("กกกที่", 3), "…กที่")
        # เหลือที่ไม่พอให้ ท แต่สระกับวรรณยุกต์ของมันไม่กินช่อง ต้องไม่ถูกทิ้งไว้ลอย ๆ
        self.assertEqual(meter.tail_fit("กที่", 1), ELLIPSIS)

    def test_no_room_gives_nothing(self):
        self.assertEqual(meter.tail_fit("สวัสดี", 0), "")


class RenderTests(unittest.TestCase):
    def test_the_line_carries_label_wave_and_words(self):
        line = meter.render((0.0, 1.0), "สวัสดี", 80, color=False)
        self.assertIn(meter.LABEL, line)
        self.assertIn(" █", line)
        self.assertTrue(line.endswith("สวัสดี"))

    def test_the_line_never_overflows_the_terminal(self):
        line = meter.render((0.5,) * meter.WAVE_WIDTH, "ก" * 200, 60, color=False)
        self.assertLessEqual(meter.display_width(line), 60)


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.screen = Screen()
        self.clock = Clock()
        self.meter = meter.Meter(stream=self.screen, clock=self.clock)

    def test_nothing_is_drawn_while_the_room_is_quiet(self):
        self.meter.feed(tone(0.0005))
        self.meter.draw()
        self.assertEqual(self.screen.getvalue(), "")

    def test_speaking_draws_the_wave(self):
        self.meter.feed(tone(0.1))
        self.meter.draw()
        self.assertIn(meter.LABEL, self.screen.getvalue())

    def test_a_short_breath_keeps_the_wave_up(self):
        self.meter.feed(tone(0.1))
        self.clock.now += meter.HOLD_SECONDS / 2
        self.assertTrue(self.meter.active)

    def test_the_wave_clears_after_the_speaker_stops(self):
        self.meter.feed(tone(0.1))
        self.meter.draw()
        self.clock.now += meter.HOLD_SECONDS + 0.1
        self.meter.draw()
        self.assertTrue(self.screen.getvalue().endswith(meter.CLEAR))

    def test_words_still_forming_keep_the_wave_up_through_a_pause(self):
        self.meter.hear("สวัสดี")
        self.clock.now += meter.HOLD_SECONDS * 5
        self.assertTrue(self.meter.active)
        self.meter.hear("")
        self.assertFalse(self.meter.active)

    def test_other_output_wipes_the_wave_line_first(self):
        self.meter.feed(tone(0.1))
        self.meter.draw()
        guarded = meter._Guarded(self.meter, self.screen)
        guarded.write("คุณ: สวัสดี\n")
        self.assertTrue(self.screen.getvalue().endswith(meter.CLEAR + "คุณ: สวัสดี\n"))

    def test_output_with_no_wave_on_screen_is_untouched(self):
        meter._Guarded(self.meter, self.screen).write("ข้อความ\n")
        self.assertEqual(self.screen.getvalue(), "ข้อความ\n")

    def test_start_and_stop_put_stdout_back(self):
        before = sys.stdout
        self.meter.start()
        self.assertIsNot(sys.stdout, before)
        self.meter.stop()
        self.assertIs(sys.stdout, before)

    def test_a_pipe_gets_no_wave_at_all(self):
        piped = meter.Meter(stream=io.StringIO())
        before = sys.stdout
        piped.start()
        self.assertIs(sys.stdout, before)
        piped.stop()


if __name__ == "__main__":
    unittest.main()
