from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT / "scripts" / "web"))

import chat  # noqa: E402
import equity_question  # noqa: E402
import spot_chart  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_reads_hands_ranges_boards_and_thai(self):
        cases = {
            "K8 vs A7 equity": (("K8", "A7"), ""),
            "k8 vs a7 equity": (("K8", "A7"), ""),
            "AKs vs QQ vs JTs %": (("AKs", "QQ", "JTs"), ""),
            "KsKc vs AhKh on Qh7h2c equity": (("KsKc", "AhKh"), "Qh7h2c"),
            "QQ+,AKs vs 22+ equity": (("QQ+,AKs", "22+"), ""),
            "AK vs any equity": (("AK", "any"), ""),
            "K8 กับ A7 อีควิตี้เท่าไหร่": (("K8", "A7"), ""),
            "what is the equity of AhAs vs KdKc": (("AhAs", "KdKc"), ""),
            "10s9s vs AA equity": (("Ts9s", "AA"), ""),
        }
        for text, (players, board) in cases.items():
            with self.subTest(text=text):
                self.assertEqual(equity_question.parse(text), equity_question.Asked(players, board))

    def test_spot_and_other_questions_are_not_equity(self):
        for text in ("BB vs BTN shove 10bb", "SB vs UTG and BTN 5bb", "plo AAKK ds", "hold K5s BTN 12bb",
                     "equity", "K8 equity"):
            with self.subTest(text=text):
                self.assertIsNone(equity_question.parse(text))


class ReplyTest(unittest.TestCase):
    def test_exact_equity_through_the_chart_chat(self):
        made = spot_chart.reply("K8 vs A7 equity")
        self.assertEqual(made.kind, "equity")
        self.assertIn("K8  39.7%", made.message)
        self.assertIn("A7  60.3%", made.message)
        self.assertIn("exact", made.message)
        self.assertIsNone(made.found)

    def test_thai_answer_and_impossible_hands(self):
        self.assertIn("ก่อน flop", spot_chart.reply("K8 กับ A7 อีควิตี้").message)
        made = spot_chart.reply("AsAh vs AsKs equity")
        self.assertEqual(made.kind, "equity_error")
        self.assertIn("K8 vs A7", made.message)

    def test_web_chat_answers_without_ai(self):
        result, _ = chat.ask("KsKc vs AhKh on Qh7h2c equity", chat.Session(ai=False),
                             chat.Tools(log=lambda line: None))
        self.assertEqual(result.kind, "equity")
        self.assertTrue(any("KsKc  53.0%" in line for line in result.lines))
        self.assertIsNone(result.chart)


if __name__ == "__main__":
    unittest.main()
