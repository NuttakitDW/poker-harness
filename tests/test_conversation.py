"""Checks the in-session memory that lets follow-up questions work."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import brain  # noqa: E402


class ConversationTests(unittest.TestCase):
    def test_adding_a_turn_leaves_the_original_untouched(self):
        empty = brain.Conversation()
        grown = empty.with_turn("user", "ถามแรก")
        self.assertEqual(empty.turns, ())
        self.assertEqual(len(grown.turns), 1)

    def test_blank_text_is_not_remembered(self):
        conversation = brain.Conversation().with_turn("assistant", "   ")
        self.assertEqual(conversation.turns, ())

    def test_only_the_most_recent_turns_are_kept(self):
        conversation = brain.Conversation()
        for index in range(brain.MAX_HISTORY_TURNS + 4):
            conversation = conversation.with_turn("user", f"ตาที่ {index}")
        self.assertEqual(len(conversation.turns), brain.MAX_HISTORY_TURNS)
        self.assertIn(str(brain.MAX_HISTORY_TURNS + 3), conversation.turns[-1].text)

    def test_long_turns_are_trimmed_to_the_character_budget(self):
        conversation = brain.Conversation()
        for _ in range(4):
            conversation = conversation.with_turn("user", "ก" * (brain.MAX_HISTORY_CHARS // 2))
        total = sum(len(turn.text) for turn in conversation.turns)
        self.assertLessEqual(total, brain.MAX_HISTORY_CHARS)
        self.assertGreaterEqual(len(conversation.turns), 2)

    def test_messages_keep_their_order_and_roles(self):
        conversation = (brain.Conversation()
                        .with_turn("user", "ถาม")
                        .with_turn("assistant", "ตอบ"))
        self.assertEqual(conversation.messages,
                         [{"role": "user", "content": "ถาม"},
                          {"role": "assistant", "content": "ตอบ"}])


class SearchTextTests(unittest.TestCase):
    def test_the_first_question_searches_on_its_own(self):
        self.assertEqual(brain.search_text("ICM คืออะไร", None), "ICM คืออะไร")

    def test_a_follow_up_borrows_the_previous_question(self):
        conversation = (brain.Conversation()
                        .with_turn("user", "เปิด 63 offsuit จาก UTG")
                        .with_turn("assistant", "หมอบเลย"))
        text = brain.search_text("แล้วถ้าเป็น button ล่ะ", conversation)
        self.assertIn("63 offsuit", text)
        self.assertIn("button", text)

    def test_an_assistant_only_history_adds_nothing(self):
        conversation = brain.Conversation().with_turn("assistant", "สวัสดีค่ะ")
        self.assertEqual(brain.search_text("ถามใหม่", conversation), "ถามใหม่")


class MessageBuildingTests(unittest.TestCase):
    def test_previous_turns_sit_between_the_system_line_and_the_question(self):
        conversation = brain.Conversation().with_turn("user", "ถามเก่า")
        messages = brain.build_messages("ถามใหม่", "บริบท", conversation)
        self.assertEqual([message["role"] for message in messages],
                         ["system", "user", "user"])
        self.assertEqual(messages[1]["content"], "ถามเก่า")
        self.assertIn("ถามใหม่", messages[-1]["content"])
        self.assertIn("บริบท", messages[-1]["content"])

    def test_a_question_without_context_is_sent_as_it_is(self):
        messages = brain.build_messages("ถามใหม่", "", reasoning=False)
        self.assertEqual(messages[-1]["content"], "ถามใหม่")

    def test_a_greeting_with_no_matching_card_still_reaches_the_model(self):
        sent = {}

        def fake_model(question, context, key, history=None, reasoning=True, **_):
            sent.update(question=question, context=context)
            yield "สวัสดีครับ"

        originals = (brain.gather, brain.preflop.context_block,
                     brain.load_api_key, brain.stream_model)
        brain.gather = lambda *a, **k: ("", [], [])
        brain.preflop.context_block = lambda wanted, **_: ""
        brain.load_api_key = lambda: "key"
        brain.stream_model = fake_model
        try:
            _, pieces = brain.stream_answer("สวัสดีลูกชุบ")
            self.assertEqual("".join(pieces), "สวัสดีครับ")
        finally:
            (brain.gather, brain.preflop.context_block,
             brain.load_api_key, brain.stream_model) = originals
        self.assertEqual(sent, {"question": "สวัสดีลูกชุบ", "context": ""})

    def test_the_format_is_repeated_every_turn_so_it_keeps_thinking(self):
        messages = brain.build_messages("ถามใหม่", "")
        self.assertIn(brain.REASONING_REMINDER, messages[-1]["content"])
        self.assertTrue(messages[-1]["content"].startswith("ถามใหม่"))

    def test_a_reply_to_an_interruption_is_asked_to_stay_short(self):
        brief = brain.build_messages("เดี๋ยวนะ", "", note=brain.BRIEF_REMINDER)[-1]["content"]
        normal = brain.build_messages("เดี๋ยวนะ", "")[-1]["content"]
        self.assertIn(brain.BRIEF_REMINDER, brief)
        self.assertNotIn(brain.BRIEF_REMINDER, normal)

    def test_brief_mode_keeps_the_system_prompt_cacheable(self):
        brief = brain.build_messages("เดี๋ยวนะ", "", note=brain.BRIEF_REMINDER)[0]["content"]
        self.assertEqual(brief, brain.build_messages("เดี๋ยวนะ", "")[0]["content"])

    def test_the_model_is_told_it_may_stay_quiet_and_listen(self):
        system = brain.build_messages("แป๊บ", "", reasoning=False)[0]["content"]
        self.assertIn(brain.LISTEN_MARKER, system)


class FollowUpChartTests(unittest.TestCase):
    """มือ PLO สี่ใบจากตาก่อน ห้ามถูกยืมไปอ่านเป็นมือ Hold'em สองใบในตารางพรีฟล็อป"""

    def charted_text(self, history: brain.Conversation, question: str) -> str:
        seen = {}

        def fake_chart(wanted, **_):
            seen["wanted"] = wanted
            return ""

        originals = (brain.gather, brain.preflop.context_block,
                     brain.load_api_key, brain.stream_model)
        brain.gather = lambda *a, **k: ("", [], [])
        brain.preflop.context_block = fake_chart
        brain.load_api_key = lambda: "key"
        brain.stream_model = lambda *a, **k: iter(())
        try:
            brain.stream_answer(question, history=history)
        finally:
            (brain.gather, brain.preflop.context_block,
             brain.load_api_key, brain.stream_model) = originals
        return seen.get("wanted", "")

    def test_a_repeat_request_after_a_plo_hand_does_not_chart_the_old_hand(self):
        history = (brain.Conversation()
                   .with_turn("user", "K J 19 ซุตเดียวครับ")
                   .with_turn("assistant", "K-J-T-9 single-suited ยังอยู่ระดับ Premium ค่ะ"))
        self.assertNotIn("K J", self.charted_text(history, "ขออีกรอบนึงนะ เป็นอะไรนะ"))

    def test_a_holdem_follow_up_still_borrows_the_previous_hand(self):
        history = (brain.Conversation()
                   .with_turn("user", "AJo ตำแหน่ง CO เปิดไหม")
                   .with_turn("assistant", "เปิดได้ค่ะ"))
        self.assertIn("AJo", self.charted_text(history, "แล้ว UTG ล่ะ"))


class SentPagesTests(unittest.TestCase):
    """หน้าต้นฉบับที่ส่งไปแล้วไม่ต้องส่งซ้ำ ไม่งั้นโมเดลเล่าเนื้อเดิมคำต่อคำ"""

    def test_pages_are_remembered_without_duplicates(self):
        conversation = (brain.Conversation()
                        .with_pages(("เล่ม ก หน้า 1", "เล่ม ข หน้า 2"))
                        .with_pages(("เล่ม ข หน้า 2", "เล่ม ค หน้า 3")))
        self.assertEqual(conversation.sent_pages,
                         ("เล่ม ก หน้า 1", "เล่ม ข หน้า 2", "เล่ม ค หน้า 3"))

    def test_remembering_pages_keeps_the_turns(self):
        conversation = brain.Conversation().with_turn("user", "ถาม").with_pages(("หน้า 1",))
        self.assertEqual(len(conversation.turns), 1)
        self.assertEqual(conversation.sent_pages, ("หน้า 1",))

    def test_adding_a_turn_keeps_the_pages_already_sent(self):
        conversation = brain.Conversation().with_pages(("หน้า 1",)).with_turn("user", "ถาม")
        self.assertEqual(conversation.sent_pages, ("หน้า 1",))


if __name__ == "__main__":
    unittest.main()
