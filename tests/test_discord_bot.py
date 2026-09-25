"""Checks the test bridge between Discord and this Mac's terminal."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))
import bot  # noqa: E402


class InviteTests(unittest.TestCase):
    def test_the_invite_link_asks_for_the_bot_scope_and_chat_permissions(self):
        url = bot.invite_url(1234)
        self.assertIn("client_id=1234", url)
        self.assertIn("scope=bot", url)
        self.assertIn(f"permissions={bot.PERMISSIONS}", url)

    def test_the_permissions_cover_reading_and_sending(self):
        for bit in (1024, 2048, 32768, 65536):  # view, send, attach files, read history
            with self.subTest(bit=bit):
                self.assertTrue(bot.PERMISSIONS & bit)


class FormatTests(unittest.TestCase):
    def test_an_incoming_message_names_the_server_channel_and_author(self):
        self.assertEqual(bot.incoming("My Server", "general", "nut", "hi"),
                         "[My Server #general] nut: hi")

    def test_a_direct_message_has_no_server(self):
        self.assertEqual(bot.incoming(None, None, "nut", "hi"), "[DM] nut: hi")


class ChartQuestionTests(unittest.TestCase):
    def test_a_mention_is_a_chart_question(self):
        self.assertEqual(bot.chart_question("<@42> BTN shove 10bb", 42, False), "BTN shove 10bb")
        self.assertEqual(bot.chart_question("<@!42> BTN shove 10bb", 42, False), "BTN shove 10bb")

    def test_the_chart_prefix_is_a_chart_question(self):
        self.assertEqual(bot.chart_question("!chart SB vs UTG 5bb", 42, False), "SB vs UTG 5bb")

    def test_every_direct_message_is_a_chart_question(self):
        self.assertEqual(bot.chart_question("BB vs BTN shove 8bb", 42, True), "BB vs BTN shove 8bb")

    def test_other_channel_chatter_is_ignored(self):
        self.assertIsNone(bot.chart_question("hello everyone", 42, False))
        self.assertIsNone(bot.chart_question("<@42>", 42, False))


def attachment(filename, content_type=None):
    return SimpleNamespace(filename=filename, content_type=content_type)


class AudioTests(unittest.TestCase):
    def test_a_voice_message_file_is_audio(self):
        found = bot.audio_attachment([attachment("voice-message.ogg", "audio/ogg")])
        self.assertEqual(found.filename, "voice-message.ogg")

    def test_audio_is_found_by_extension_when_the_type_is_missing(self):
        self.assertIsNotNone(bot.audio_attachment([attachment("hand.m4a")]))

    def test_pictures_are_not_audio(self):
        self.assertIsNone(bot.audio_attachment([attachment("chart.png", "image/png")]))

    def test_voice_messages_and_direct_audio_are_answered(self):
        self.assertTrue(bot.answers_audio(voice=True, direct=False, text="", bot_id=42))
        self.assertTrue(bot.answers_audio(voice=False, direct=True, text="", bot_id=42))

    def test_a_plain_audio_file_in_a_channel_needs_a_mention_or_prefix(self):
        self.assertFalse(bot.answers_audio(voice=False, direct=False, text="", bot_id=42))
        self.assertTrue(bot.answers_audio(voice=False, direct=False, text="<@42>", bot_id=42))
        self.assertTrue(bot.answers_audio(voice=False, direct=False, text="!chart", bot_id=42))

    def test_the_reply_says_what_was_heard(self):
        self.assertEqual(bot.heard_line("BTN shove 10bb"), "ได้ยินว่า: BTN shove 10bb")


class TerminalCommandTests(unittest.TestCase):
    def test_plain_text_is_sent_to_discord(self):
        self.assertEqual(bot.terminal_command("สวัสดีจาก Mac"), ("send", "สวัสดีจาก Mac"))

    def test_to_switches_the_target_channel(self):
        self.assertEqual(bot.terminal_command("/to 998877"), ("to", "998877"))

    def test_channels_lists_where_the_bot_can_talk(self):
        self.assertEqual(bot.terminal_command("/channels"), ("channels", ""))

    def test_blank_lines_do_nothing(self):
        self.assertEqual(bot.terminal_command("   "), ("skip", ""))


if __name__ == "__main__":
    unittest.main()
