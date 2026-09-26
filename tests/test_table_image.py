from pathlib import Path
import json
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import spot_chart  # noqa: E402
import table_image  # noqa: E402

# คำตอบจริงของ deepseek-v4-flash-vision-exp ต่อรูป AoF #AF1358107095 (2026-09-26) ปิด thinking แล้วห่อด้วย ```json
FINISHED_AOF = """```json
{
  "site": "Natural8",
  "game": "NLH All-In or Fold",
  "stakes": "$0.05 / $0.10",
  "players": [
    {"name": "Nuttakit Ku...", "stack_bb": 10, "bet_bb": 0, "action": null, "cards": ["Th", "6d"]},
    {"name": "s6gma69420", "stack_bb": 0, "bet_bb": 0, "action": null, "cards": ["Kh", "7d"]},
    {"name": "anatol6989", "stack_bb": 0, "bet_bb": 0, "action": null, "cards": ["Qh", "8d"]},
    {"name": "Mania90", "stack_bb": 10, "bet_bb": 0, "action": null, "cards": null}
  ],
  "button": "Nuttakit Ku...",
  "hand_finished": true
}
```"""


def player(name, stack=10, bet=0, action=None, cards=None):
    return {"name": name, "stack_bb": stack, "bet_bb": bet, "action": action, "cards": cards}


def table(players, button, game="All-in or Fold", finished=False):
    return json.dumps({"game": game, "players": players, "button": button,
                       "hand_finished": finished})


class ParseTests(unittest.TestCase):
    def test_a_fenced_reply_is_read(self):
        read = table_image.parse(FINISHED_AOF)
        self.assertTrue(read.aof)
        self.assertTrue(read.finished)
        self.assertEqual(len(read.seats), 4)
        self.assertEqual(read.button, 0)
        self.assertEqual(read.seats[0].cards, ("Th", "6d"))

    def test_a_tournament_is_not_aof(self):
        read = table_image.parse(table([player("me"), player("v")], "me", game="MTT Bounty"))
        self.assertFalse(read.aof)

    def test_not_json_is_an_error(self):
        with self.assertRaises(table_image.TableError):
            table_image.parse("I cannot see a poker table")

    def test_one_player_is_not_a_table(self):
        with self.assertRaises(table_image.TableError):
            table_image.parse(table([player("me")], "me"))

    def test_an_unknown_button_is_an_error(self):
        with self.assertRaises(table_image.TableError):
            table_image.parse(table([player("me"), player("v")], "nobody"))

    def test_bad_cards_are_dropped_not_fatal(self):
        read = table_image.parse(table([player("me", cards=["??", "6d"]), player("v")], "me"))
        self.assertIsNone(read.seats[0].cards)


class SeatTests(unittest.TestCase):
    def test_clockwise_from_the_button_is_sb_then_bb(self):
        read = table_image.parse(FINISHED_AOF)
        self.assertEqual(table_image.seat_names(read), ("BTN", "SB", "BB", "CO"))

    def test_hero_in_the_big_blind_of_six(self):
        names = [f"p{i}" for i in range(6)]
        read = table_image.parse(table([player(n) for n in names], "p4"))
        self.assertEqual(table_image.seat_names(read), ("BB", "UTG", "HJ", "CO", "BTN", "SB"))

    def test_heads_up_button_is_the_small_blind(self):
        read = table_image.parse(table([player("me"), player("v")], "v"))
        self.assertEqual(table_image.seat_names(read), ("BB", "SB"))


class HandTests(unittest.TestCase):
    def test_hands(self):
        self.assertEqual(table_image.hand_of(("Th", "6d")), "T6o")
        self.assertEqual(table_image.hand_of(("6c", "Kc")), "K6s")
        self.assertEqual(table_image.hand_of(("Qs", "Qd")), "QQ")
        self.assertIsNone(table_image.hand_of(None))


class QuestionTests(unittest.TestCase):
    def test_finished_hand_asks_heros_seat_and_hand(self):
        read = table_image.parse(FINISHED_AOF)
        self.assertEqual(table_image.question(read), "aof 4 handed BTN 10bb hold T6o")

    def test_facing_one_shove(self):
        players = [player("me", stack=9, bet=1, cards=["Ah", "Jd"]),
                   player("u", stack=0, bet=10, action="all-in"),
                   player("c", action="fold"), player("b", stack=9.5, bet=0.5)]
        read = table_image.parse(table(players, "c"))
        # me=BB u=CO c=BTN b=SB
        self.assertEqual(table_image.question(read), "aof 4 handed BB vs CO shove 10bb hold AJo")

    def test_facing_a_shove_and_a_call_in_action_order(self):
        players = [player("me", stack=9.5, bet=0.5), player("bb", stack=9, bet=1),
                   player("co", stack=0, bet=10, action="all-in"),
                   player("btn", stack=0, bet=10, action="all-in")]
        read = table_image.parse(table(players, "btn"))
        self.assertEqual(table_image.question(read), "aof 4 handed SB vs CO and BTN 10bb")

    def test_effective_stack_is_the_covered_amount(self):
        players = [player("me", stack=20), player("v", stack=7), player("w", stack=0, action="fold")]
        read = table_image.parse(table(players, "me", game="Spin"))
        self.assertEqual(table_image.question(read), "3 handed BTN 7bb")

    def test_heads_up_is_named(self):
        read = table_image.parse(table([player("me", stack=9.5, bet=0.5), player("v")], "me"))
        self.assertEqual(table_image.question(read), "aof heads-up SB 10bb")

    def test_a_busted_hero_has_no_stack(self):
        read = table_image.parse(table([player("me", stack=0), player("v")], "me", finished=True))
        self.assertEqual(table_image.question(read), "aof heads-up SB")

    def test_actions_are_ignored_once_the_hand_is_over(self):
        players = [player("me"), player("v", stack=0, action="all-in"), player("w")]
        read = table_image.parse(table(players, "w", finished=True))
        self.assertNotIn("vs", table_image.question(read))

    def test_the_question_gets_a_chart(self):
        made = spot_chart.reply(table_image.question(table_image.parse(FINISHED_AOF)))
        self.assertEqual(made.kind, "chart")
        self.assertEqual(made.found.chart["hero"], "BTN")
        self.assertEqual(made.found.hands, ("T6o",))


class ReadTests(unittest.TestCase):
    def test_the_request_asks_the_vision_model_without_thinking(self):
        sent = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": FINISHED_AOF}}]}).encode()

        def fake_urlopen(request, timeout):
            sent["body"] = json.loads(request.data)
            sent["auth"] = request.get_header("Authorization")
            return Response()

        with mock.patch.object(table_image.urllib.request, "urlopen", fake_urlopen):
            read = table_image.read(b"png-bytes", "image/png", "key-1")
        self.assertEqual(read.button, 0)
        self.assertEqual(sent["auth"], "Bearer key-1")
        self.assertEqual(sent["body"]["model"], table_image.MODEL)
        self.assertEqual(sent["body"]["thinking"], {"type": "disabled"})
        image = sent["body"]["messages"][0]["content"][0]["image_url"]["url"]
        self.assertTrue(image.startswith("data:image/png;base64,"))

    def test_a_network_failure_is_a_table_error(self):
        def broken(request, timeout):
            raise table_image.urllib.error.URLError("down")

        with mock.patch.object(table_image.urllib.request, "urlopen", broken):
            with self.assertRaises(table_image.TableError):
                table_image.read(b"x", "image/png", "k")


if __name__ == "__main__":
    unittest.main()
