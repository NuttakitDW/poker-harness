"""AI mode: the model writes the chart query, the solver still draws the chart."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
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

    def test_shove_is_spelled_the_way_players_say_it(self):
        for wrong in ("ชูฟ", "ชู้ฟ"):
            with self.subTest(wrong=wrong):
                made = assistant.parse(f'{{"say": "ดูเรนจ์{wrong} HJ ให้นะครับ", "query": null}}')
                self.assertEqual(made.say, "ดูเรนจ์โชฟ HJ ให้นะครับ")

    def test_solver_stays_in_english(self):
        for wrong in ("โซลเวอร์", "โซลเว่อร์", "ซอลเวอร์"):
            with self.subTest(wrong=wrong):
                made = assistant.parse(f'{{"say": "แก้ด้วย{wrong}ของเราเอง", "query": null}}')
                self.assertEqual(made.say, "แก้ด้วย solver ของเราเอง")

    def test_the_prompt_keeps_technical_terms_in_english(self):
        self.assertIn("never transliterate", assistant.SYSTEM)

    def test_the_prompt_gives_the_thai_spelling_of_shove(self):
        self.assertIn("โชฟ", assistant.SYSTEM)

    def test_rejects_answers_that_break_the_contract(self):
        for content in ("not json", '{"query": "BTN 10bb"}', '{"say": ""}', "[1]", None):
            with self.subTest(content=content), self.assertRaises(assistant.AssistantError):
                assistant.parse(content)


class InjectionTests(unittest.TestCase):
    def test_links_are_removed(self):
        for say in ("free nitro https://evil.example/x now", "go to www.evil.com now",
                    "claim at discord.gg/abc123 now", "see [your prize](https://evil.example) now",
                    "visit bit.ly/xyz now", "open hxxp://evil.ru/login now"):
            with self.subTest(say=say):
                cleaned = assistant.safe_text(say)
                for bad in ("http", "www", "discord.gg", "bit.ly", "evil", "hxxp"):
                    self.assertNotIn(bad, cleaned)
                self.assertTrue(cleaned.endswith("now"))

    def test_mentions_are_removed(self):
        cleaned = assistant.safe_text("@everyone @here <@123> <@!456> <@&789> <#42> hi")
        for bad in ("@", "<", "123", "789"):
            self.assertNotIn(bad, cleaned)
        self.assertTrue(cleaned.endswith("hi"))

    def test_poker_words_survive(self):
        text = "BB vs SB shove 5.5bb ante 0.1bb, K9o, pool 15,000 THB"
        self.assertEqual(assistant.safe_text(text), text)

    def test_the_model_reply_is_cleaned(self):
        made = assistant.parse('{"say": "@everyone free nitro https://evil.example", "query": null}')
        self.assertEqual(made.say, "everyone free nitro")
        self.assertEqual(assistant.parse('{"say": "https://evil.example", "query": null}').say, "…")

    def test_the_bot_can_only_ping_the_person_it_replies_to(self):
        allowed = bot.ALLOWED_MENTIONS
        self.assertEqual((allowed.everyone, allowed.roles, allowed.users, allowed.replied_user),
                         (False, False, False, True))
        self.assertIs(bot.Bridge(None).allowed_mentions, allowed)


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

    def test_a_problem_is_told_in_the_language_the_user_wrote(self):
        made = assistant.answer("SB 13.2bb UTG all in มา ใกล้เข้าเงิน 10 คนลง", spot_chart.reply,
                                key="k", crafter=model_says(
                                    "ดูให้ครับ", "SB vs UTG shove 13.2bb icm bubble field 10"))
        self.assertEqual(made.made.kind, "seat_not_at_table")
        self.assertIn("เหลือ 6 คน", made.made.message)

    def test_a_spot_the_solver_can_answer_is_answered_even_if_the_model_asks_for_more(self):
        made = assistant.answer("BTN shove 10bb ใกล้เข้าเงิน", spot_chart.reply, key="k",
                                crafter=model_says("ถือไพ่อะไรครับ buy-in เท่าไหร่", None))
        self.assertEqual(made.made.kind, "chart")
        self.assertEqual(made.query, "BTN shove 10bb ใกล้เข้าเงิน")
        self.assertEqual(made.say, assistant.ANSWERED_DIRECTLY["TH"])
        self.assertEqual(json.loads(made.history[-1].assistant)["query"], made.query)

    def test_a_remembered_spot_does_not_turn_a_question_into_a_chart(self):
        # the fallback is for a message that is itself a spot; the remembered spot alone must not trigger it
        remembered = preflop.Request(game="tournament", hero="BTN", stack=10, scenario="RFI", pushfold=True)
        made = assistant.answer("อยากรู้เรื่องความน่าเชื่อถือ", spot_chart.reply, memory=remembered, key="k",
                                crafter=model_says("เทียบกับชาร์ตของ Jonathan Little ตรงกัน 162 จาก 169 มือ", None))
        self.assertIsNone(made.made)
        self.assertEqual(made.say, "เทียบกับชาร์ตของ Jonathan Little ตรงกัน 162 จาก 169 มือ")

    def test_a_spot_in_the_message_still_uses_the_remembered_details(self):
        remembered = preflop.Request(game="tournament", hero="BTN", stack=10, scenario="RFI", pushfold=True,
                                     payouts=(50.0, 30.0, 20.0))
        made = assistant.answer("CO shove 8bb", spot_chart.reply, memory=remembered, key="k",
                                crafter=model_says("ถือไพ่อะไรครับ", None))
        self.assertEqual(made.made.kind, "chart")

    def test_a_question_for_a_vital_missing_stack_is_kept(self):
        made = assistant.answer("SB เจอ UTG all in", spot_chart.reply, key="k",
                                crafter=model_says("เหลือกี่ bb ครับ", None))
        self.assertIsNone(made.made)
        self.assertEqual(made.say, "เหลือกี่ bb ครับ")

    def test_the_prompt_says_only_seat_and_stack_are_vital(self):
        self.assertIn("Only a seat and a stack are vital", assistant.SYSTEM)

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


SUMMARY = {
    "reference": "Jonathan Little, PokerCoaching.com push/fold charts (10% ante table)",
    "spot": "UTG first in, 10bb, 9-handed, ante 10% of the big blind per player, chip EV",
    "matched": 162, "total": 169, "ours_percent": 13.7, "theirs_percent": 14.3,
    "exploitability_bb": 0.0007, "differ": ["A8s", "ATo", "22"], "close_calls": 2, "close_bb": 0.05,
    "widest": {"hand": "ATo", "gap_bb": -0.139},
    "stacks": {"from": 5, "to": 15, "matched_min": 160, "matched_max": 166},
}


class MethodFactsTests(unittest.TestCase):
    """Asked whether the charts can be trusted, the model answers from the Method page's real numbers."""

    def write(self, folder, data):
        path = Path(folder) / "method-summary.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_the_facts_carry_the_comparison_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            facts = assistant.method_facts(self.write(folder, SUMMARY))
        for piece in ("Jonathan Little", "162 of 169", "95.9%", "13.7%", "14.3%", "0.0007",
                      "ATo", "160-166", "วิธีคำนวณ"):
            with self.subTest(piece=piece):
                self.assertIn(piece, facts)

    def test_the_facts_say_who_jonathan_little_is(self):
        with tempfile.TemporaryDirectory() as folder:
            facts = assistant.method_facts(self.write(folder, SUMMARY))
        for piece in ("founder and owner of PokerCoaching", "many players study", "Do not give numbers"):
            with self.subTest(piece=piece):
                self.assertIn(piece, facts)

    def test_no_summary_means_no_facts(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(assistant.method_facts(Path(folder) / "missing.json"), "")
            self.assertEqual(assistant.method_facts(self.write(folder, {"matched": 1})), "")

    def test_the_facts_reach_the_model(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(assistant, "METHOD_SUMMARY", self.write(folder, SUMMARY)):
                system = assistant.build_messages("ชาร์ตนี้น่าเชื่อถือแค่ไหน", (), None)[0]["content"]
        self.assertIn("162 of 169", system)

    def test_the_prompt_says_to_answer_trust_questions_from_the_facts(self):
        self.assertIn("Method facts", assistant.SYSTEM)

    def test_the_shipped_summary_matches_the_method_page(self):
        facts = assistant.method_facts(assistant.METHOD_SUMMARY)
        self.assertIn("Jonathan Little", facts)
