"""Checks that the equity tool agrees with pokerkit and that ลูกชุบ can call it mid-answer."""

from pathlib import Path
import io
import itertools
import json
import random
import sys
import tempfile
import unittest

import numpy
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import brain  # noqa: E402
import equity  # noqa: E402
import equity_eval  # noqa: E402
import tools  # noqa: E402
from pokerkit import Card, Deck, StandardHighHand, calculate_equities, parse_range  # noqa: E402


def cards(text: str) -> list:
    return list(Card.parse(text))


def pokerkit_equity(first: str, second: str, board: str) -> tuple[float, float]:
    """ไล่ทุก runout ด้วย StandardHighHand ของ pokerkit ตรง ๆ ช้าแต่เป็นคำตอบอ้างอิง"""
    hands = [cards(first), cards(second)]
    known = cards(board)
    used = set(itertools.chain(*hands, known))
    left = [card for card in Deck.STANDARD if card not in used]
    totals = [0.0, 0.0]
    count = 0
    for extra in itertools.combinations(left, 5 - len(known)):
        full = known + list(extra)
        a, b = (StandardHighHand.from_game(hand, full) for hand in hands)
        totals[0] += 1.0 if a > b else 0.5 if a == b else 0.0
        totals[1] += 1.0 if b > a else 0.5 if a == b else 0.0
        count += 1
    return totals[0] / count, totals[1] / count


class MemoIsolation(unittest.TestCase):
    """ทุกเทสต์ใช้ sqlite ของตัวเอง ผลที่จำไว้ในเครื่องจึงไม่ทำให้เทสต์ผ่านแบบบังเอิญ"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(equity, "MEMO", equity.Memo(Path(folder.name) / "memo.sqlite"))
        patcher.start()
        self.addCleanup(patcher.stop)


class HandStrengthTests(unittest.TestCase):
    def test_every_random_seven_cards_rank_like_pokerkit(self):
        chooser = random.Random(7)
        deck = list(range(52))
        for _ in range(3000):
            dealt = chooser.sample(deck, 7)
            hole, board = tuple(dealt[:2]), dealt[2:]
            boards = equity_eval.boards_of(numpy.array([board], dtype="int8"))
            ours = int(equity_eval.strength(hole, boards)[0])
            text = [equity_eval.card_text([c]) for c in dealt]
            theirs = StandardHighHand.from_game("".join(text[:2]), "".join(text[2:]))
            self.assertEqual(ours, theirs.entry.index, text)


class ExactEquityTests(MemoIsolation):
    def test_kings_against_aces_preflop(self):
        result = equity.calculate(["KsKc", "AcAh"])
        kings, aces = result.players
        self.assertTrue(result.exact)
        self.assertEqual(result.runouts, 1_712_304)
        self.assertAlmostEqual(kings.equity + aces.equity, 1.0, places=12)
        self.assertEqual(round(kings.equity * 100, 2), 18.05)
        self.assertEqual(round(aces.equity * 100, 2), 81.95)
        self.assertEqual(round(kings.tie * 100, 2), 0.46)

    def test_flop_equity_matches_brute_force_with_pokerkit(self):
        for first, second, board in (("AhKh", "7c7d", "Th9h2c"), ("QsJs", "AdAc", "Ks8s2d"),
                                     ("5c5d", "6h7h", "8h9c5s")):
            result = equity.calculate([first, second], board)
            expected = pokerkit_equity(first, second, board)
            self.assertAlmostEqual(result.players[0].equity, expected[0], places=12)
            self.assertAlmostEqual(result.players[1].equity, expected[1], places=12)

    def test_turn_and_river_boards(self):
        turn = equity.calculate(["AhKh", "7c7d"], "Th9h2c3d")
        self.assertEqual(turn.runouts, 44)
        river = equity.calculate(["AhKh", "7c7d"], "Th9h2c3d4h")
        self.assertEqual((river.players[0].equity, river.runouts), (1.0, 1))

    def test_a_split_pot_on_the_board(self):
        result = equity.calculate(["2c3d", "4h5s"], "AhKhQhJhTh")
        self.assertEqual([player.tie for player in result.players], [1.0, 1.0])
        self.assertEqual([player.equity for player in result.players], [0.5, 0.5])

    def test_range_versus_range_averages_every_legal_matchup(self):
        result = equity.calculate(["AA", "KK"])
        self.assertEqual((result.players[0].combos, result.matchups), (6, 36))
        # equity ของ range คือค่าเฉลี่ยของทุกคู่มือที่เกิดขึ้นได้ ซึ่งแต่ละคู่มีจำนวนบอร์ดเท่ากัน
        pairs = [equity.calculate(["".join(a), "".join(k)]).players[0].equity
                 for a in itertools.combinations(("Ac", "Ad", "Ah", "As"), 2)
                 for k in itertools.combinations(("Kc", "Kd", "Kh", "Ks"), 2)]
        self.assertAlmostEqual(result.players[0].equity, sum(pairs) / len(pairs), places=12)

    def test_postflop_range_matrix_matches_pair_by_pair(self):
        board = "Qh7c2d"
        result = equity.calculate(["AK", "QQ,JTs,7h6h"], board)
        known = equity.parse_cards(board)
        shares = [equity.exact_share([a, b], known)
                  for a in equity.parse_hand_range("AK") for b in equity.parse_hand_range("QQ,JTs,7h6h")
                  if not (set(a) | set(b)) & set(known) and not set(a) & set(b)]
        self.assertEqual(result.matchups, len(shares))
        for index in range(2):
            self.assertAlmostEqual(result.players[index].equity,
                                   sum(s.equity[index] for s in shares) / len(shares), places=12)
            self.assertAlmostEqual(result.players[index].tie,
                                   sum(s.tie[index] for s in shares) / len(shares), places=12)

    def test_canonical_keys_only_join_suit_swaps(self):
        pairs = numpy.array([[[48, 49], [44, 45]],    # AcAd v KcKd
                             [[50, 51], [46, 47]],    # AhAs v KhKs
                             [[48, 49], [46, 47]]])   # AcAd v KhKs
        first, second, third = equity.canonical_keys(pairs, ())
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)

    def test_range_result_agrees_with_pokerkit_sampling(self):
        result = equity.calculate(["QQ+,AKs", "JJ-99,AQs"])
        sampled = calculate_equities((parse_range("QQ+,AKs"), parse_range("JJ-99,AQs")), (),
                                     2, 5, Deck.STANDARD, (StandardHighHand,), sample_count=4000)
        self.assertLess(abs(result.players[0].equity - sampled[0]), 0.03)

    def test_three_players_share_the_whole_pot(self):
        result = equity.calculate(["AsAh", "KsKh", "QdJd"])
        self.assertAlmostEqual(sum(player.equity for player in result.players), 1.0, places=12)

    def test_suit_swapped_matchups_reuse_one_result(self):
        equity.calculate(["KsKc", "AcAh"])
        with mock.patch.object(equity, "exact_share", side_effect=AssertionError("recomputed")):
            again = equity.calculate(["KhKd", "AdAs"])
        self.assertEqual(round(again.players[1].equity * 100, 2), 81.95)

    def test_too_many_new_matchups_are_sampled_and_labelled(self):
        with mock.patch.object(equity, "EXACT_BUDGET_SECONDS", 0.5):
            result = equity.calculate(["QQ+,AK", "22+"])
        self.assertFalse(result.exact)
        self.assertGreater(result.margin, 0)
        self.assertLess(result.matchups_used, result.matchups)


class InputTests(MemoIsolation):
    def test_bad_input_is_explained(self):
        for players, board in ((["KsKc"], ""), (["KsKc", "KsKd"], ""), (["Zz", "AA"], ""),
                               (["KK", "AA"], "Ah"), (["AhAs", "KK"], "AhKdQc")):
            with self.assertRaises(equity.EquityError):
                equity.calculate(players, board)

    def test_any_two_cards(self):
        self.assertEqual(len(equity.parse_hand_range("any")), 1326)


class ToolTests(MemoIsolation):
    def test_the_tool_logs_the_call_and_returns_numbers(self):
        with mock.patch.object(tools, "_log") as logged:
            reply = json.loads(tools.run(tools.EQUITY_TOOL, json.dumps({"players": ["KsKc", "AcAh"]})))
        self.assertEqual([p["equity_pct"] for p in reply["players"]], [18.05, 81.95])
        self.assertIn("ลูกชุบกำลังเรียก poker_equity: KsKc vs AcAh", logged.call_args_list[0].args[0])

    def test_bad_arguments_come_back_as_an_error_for_the_model(self):
        with mock.patch.object(tools, "_log"):
            self.assertIn("error", json.loads(tools.run(tools.EQUITY_TOOL, "{not json")))
            self.assertIn("error", json.loads(tools.run(tools.EQUITY_TOOL, '{"players": ["KK"]}')))
            self.assertIn("error", json.loads(tools.run("nope", "{}")))


def stream_lines(*chunks):
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n"
    return io.BytesIO(body.encode("utf-8"))


class ToolCallStreamTests(MemoIsolation):
    def test_a_tool_call_runs_then_the_model_answers_with_the_result(self):
        arguments = json.dumps({"players": ["KsKc", "AcAh"]})
        first = stream_lines(
            {"choices": [{"delta": {"content": "คิด: ต้องคำนวณ"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {
                "name": "poker_equity", "arguments": arguments[:10]}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
                "arguments": arguments[10:]}}]}}]})
        second = stream_lines({"choices": [{"delta": {"content": "คิด: ได้ตัวเลข\nตอบ: AA 81.9%"}}]})
        with mock.patch.object(brain, "_open_stream", side_effect=[first, second]) as opened, \
                mock.patch.object(brain, "_charge"), mock.patch.object(tools, "_log"):
            spoken = "".join(brain.stream_model("q", "", "key"))
        # ข้อความก่อนเรียกเครื่องมือถูกทิ้ง เหลือแต่คำตอบที่มีตัวเลขจริง
        self.assertEqual(spoken, "คิด: ได้ตัวเลข\nตอบ: AA 81.9%")
        extra = opened.call_args_list[1].args[6]
        self.assertEqual(extra[0]["tool_calls"][0]["function"]["arguments"], arguments)
        result = json.loads(extra[1]["content"])
        self.assertEqual((extra[1]["tool_call_id"], result["players"][1]["equity_pct"]),
                         ("call_1", 81.95))

    def test_the_request_offers_the_tool_until_the_last_round(self):
        offered = json.loads(brain._request("q", "", "key").data)
        self.assertEqual(offered["tools"][0]["function"]["name"], "poker_equity")
        final = json.loads(brain._request("q", "", "key", allow_tools=False).data)
        self.assertEqual(final["tool_choice"], "none")

    def test_tool_markup_written_as_text_is_never_spoken(self):
        leak = stream_lines(
            {"choices": [{"delta": {"content": "<｜｜DS"}}]},
            {"choices": [{"delta": {"content": "ML｜｜ calls> <｜｜DSML｜｜ invoke name=\"poker_equity\">"}}]})
        with mock.patch.object(brain, "_open_stream", return_value=leak), \
                mock.patch.object(brain, "_charge"), mock.patch("builtins.print"):
            spoken = "".join(brain.stream_model("q", "", "key"))
        self.assertNotIn("DSML", spoken)
        self.assertIn(brain.TOOL_LEAK_REPLY, spoken.split(brain.SAY_MARKER)[-1])

    def test_an_empty_answer_after_failed_tool_rounds_still_speaks(self):
        failing = json.dumps({"players": ["KK"]})
        def call():
            return stream_lines({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c",
                                  "function": {"name": "poker_equity", "arguments": failing}}]}}]})
        empty = stream_lines({"choices": [{"delta": {"content": "คิด: ต้องเรียกเครื่องมือ\n\nตอบ:"}}]})
        replies = [call() for _ in range(brain.MAX_TOOL_ROUNDS)] + [empty]
        with mock.patch.object(brain, "_open_stream", side_effect=replies), \
                mock.patch.object(brain, "_charge"), mock.patch.object(tools, "_log"):
            spoken = "".join(brain.stream_model("q", "", "key"))
        # ตัวคั่นส่วนพูดต้องมีครั้งเดียว ไม่งั้นคำว่า "ตอบ:" จะถูกอ่านออกเสียง
        self.assertEqual(spoken.count(brain.SAY_MARKER), 1)
        self.assertIn(brain.TOOL_LEAK_REPLY, spoken.split(brain.SAY_MARKER)[-1])

    def test_standard_kicker_spans_are_read(self):
        # โมเดลเขียน A7s-A4s ซึ่ง pokerkit ไม่รับ เคยพังสองรอบติดจนหมดสิทธิ์เรียกเครื่องมือ
        self.assertEqual(len(equity.parse_hand_range("A7s-A4s")), 16)
        self.assertEqual(len(equity.parse_hand_range("KJs-K7s,A9o-A8o,T9s-54s")), 20 + 24 + 24)


if __name__ == "__main__":
    unittest.main()
