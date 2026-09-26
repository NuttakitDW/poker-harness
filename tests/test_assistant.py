"""AI mode: the model writes the chart query, the solver still draws the chart."""

import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))
import assistant  # noqa: E402
import bot  # noqa: E402
import preflop  # noqa: E402
import spot_chart  # noqa: E402


def model_says(say, query):
    """A stand-in for DeepSeek that always answers the same thing."""
    return lambda text, history, memory, key: assistant.Crafted(say, query)


def broken(text, history, memory, key):
    raise assistant.AssistantError("down")


class ToggleTests(unittest.TestCase):
    def test_on_and_off_in_both_prefixes(self):
        for said, on in (("/ai-on", True), ("!ai-on", True), ("/AI-OFF", False), ("!ai-off", False)):
            with self.subTest(said=said):
                self.assertIs(assistant.toggle(said), on)
        self.assertIsNone(assistant.toggle("BTN 10bb"))

    def test_the_help_lists_both_commands(self):
        for text in (spot_chart.HELP_TEXT["th"], spot_chart.HELP_TEXT["en"], bot.help_message("!help en")):
            self.assertIn("ai-on", text)
            self.assertIn("ai-off", text)


class ParseTests(unittest.TestCase):
    def test_reads_say_and_query(self):
        made = assistant.parse('{"say": "ดูให้นะ", "query": " BB vs SB shove 10bb icm "}')
        self.assertEqual(made, assistant.Crafted("ดูให้นะ", "BB vs SB shove 10bb icm"))

    def test_an_empty_query_means_no_chart(self):
        for query in ("null", '""', '"  "', "5"):
            with self.subTest(query=query):
                self.assertIsNone(assistant.parse(f'{{"say": "สแตกเท่าไร", "query": {query}}}').query)

    def test_rejects_answers_that_break_the_contract(self):
        for content in ("not json", '{"query": "BTN 10bb"}', '{"say": ""}', "[1]", None):
            with self.subTest(content=content), self.assertRaises(assistant.AssistantError):
                assistant.parse(content)


class MessagesTests(unittest.TestCase):
    def test_the_remembered_spot_and_recent_turns_go_to_the_model(self):
        history = tuple(assistant.Turn(f"q{i}", "{}") for i in range(10))
        messages = assistant.build_messages("12bb", history, preflop.Request(hero="BTN", stack=10))
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(len(messages), 1 + 2 * assistant.MAX_HISTORY_TURNS + 1)
        self.assertIn('"hero": "BTN"', messages[-1]["content"])
        self.assertTrue(messages[-1]["content"].endswith("12bb"))

    def test_nothing_remembered(self):
        self.assertEqual(assistant.remembered(None), "none")


class AnswerTests(unittest.TestCase):
    def test_the_crafted_query_is_solved(self):
        made = assistant.answer("ผมอยู่ BB มี 10bb SB ยัดมา ใกล้เข้าเงิน", spot_chart.reply, key="k",
                                crafter=model_says("ดู BB เจอ SB บน bubble ให้นะ", "BB vs SB shove 10bb bubble"))
        self.assertEqual(made.query, "BB vs SB shove 10bb bubble")
        self.assertEqual(made.made.kind, "chart")
        self.assertIn("bubble", made.made.note)
        self.assertEqual(json.loads(made.history[-1].assistant)["query"], made.query)

    def test_no_query_is_just_talk(self):
        made = assistant.answer("สวัสดี", spot_chart.reply, key="k",
                                crafter=model_says("สวัสดีครับ ถาม spot มาได้เลย", None))
        self.assertIsNone(made.made)
        self.assertEqual(len(made.history), 1)

    def test_a_broken_model_falls_back_to_the_basic_reader(self):
        made = assistant.answer("BTN shove 10bb", spot_chart.reply, key="k", crafter=broken)
        self.assertEqual(made.say, assistant.FELL_BACK)
        self.assertEqual(made.made.kind, "chart")
        self.assertEqual(made.history, ())

    def test_no_key_falls_back_without_calling_the_model(self):
        with mock.patch.object(assistant, "api_key", return_value=None):
            made = assistant.answer("BTN shove 10bb", spot_chart.reply, crafter=broken)
        self.assertEqual(made.say, assistant.FELL_BACK)

    def test_history_is_capped(self):
        history = tuple(assistant.Turn("q", "{}") for _ in range(assistant.MAX_HISTORY_TURNS))
        made = assistant.answer("hi", spot_chart.reply, history, key="k", crafter=model_says("hi", None))
        self.assertEqual(len(made.history), assistant.MAX_HISTORY_TURNS)
        self.assertEqual(made.history[-1].user, "hi")


class TerminalTests(unittest.TestCase):
    def test_ai_answer_shows_the_talk_the_query_and_the_chart(self):
        with mock.patch.object(assistant, "craft", model_says("ดูให้นะ", "BTN shove 10bb")), \
                mock.patch.object(assistant, "api_key", return_value="k"):
            shown, found, history = spot_chart.ai_answer("ปุ่ม 10bb ยัดได้ไหม", color=False)
        self.assertTrue(shown.startswith("ดูให้นะ\nquery: BTN shove 10bb"))
        self.assertEqual(found.request.hero, "BTN")
        self.assertEqual(len(history), 1)


class BotTests(unittest.TestCase):
    def test_ai_is_on_by_default_and_toggles_per_person(self):
        bridge = bot.Bridge.__new__(bot.Bridge)
        bridge.ai_off, bridge.history, bridge.memory = set(), {(1, 2): ("x",)}, {}
        self.assertEqual(bridge._toggle_ai((1, 2), False), assistant.TURNED[False])
        self.assertIn((1, 2), bridge.ai_off)
        self.assertNotIn((1, 2), bridge.history)
        bridge._toggle_ai((1, 2), True)
        self.assertNotIn((1, 2), bridge.ai_off)

    def test_ai_off_goes_straight_to_the_solver(self):
        bridge = bot.Bridge.__new__(bot.Bridge)
        bridge.ai_off, bridge.history, bridge.memory = {(1, 2)}, {}, {}
        with mock.patch.object(assistant, "craft", broken):
            made, lines, logged = asyncio.run(bridge._ask("BTN shove 10bb", (1, 2), ai=True))
        self.assertEqual((made.kind, lines, logged), ("chart", [], {}))

    def test_ai_on_shows_the_crafted_query(self):
        bridge = bot.Bridge.__new__(bot.Bridge)
        bridge.ai_off, bridge.history, bridge.memory = set(), {}, {}
        with mock.patch.object(assistant, "craft", model_says("ดูให้นะ", "BTN shove 10bb")), \
                mock.patch.object(assistant, "api_key", return_value="k"):
            made, lines, logged = asyncio.run(bridge._ask("ปุ่ม 10bb", (1, 2), ai=True))
        self.assertEqual(lines, ["ดูให้นะ", "query: BTN shove 10bb"])
        self.assertEqual(logged, {"ai_query": "BTN shove 10bb"})
        self.assertEqual(len(bridge.history[(1, 2)]), 1)


if __name__ == "__main__":
    unittest.main()
