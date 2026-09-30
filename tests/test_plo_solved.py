from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "voice"))

import plo_solved  # noqa: E402
import spot_chart  # noqa: E402
from plo_premium_proof.preflop_chart import CHART_DIR, SpotError, spot_events  # noqa: E402

HAVE_CHARTS = all((CHART_DIR / name / "meta.json").exists() for name in ("20bb", "mtt40"))


class MissingChartTest(unittest.TestCase):
    def test_a_server_without_charts_answers_instead_of_crashing(self):
        from unittest import mock
        with mock.patch.object(plo_solved, "chart", side_effect=FileNotFoundError):
            made = plo_solved.answer("plo 40bb UTG AsKsQd9c", lang="EN")
        self.assertEqual(made.status, "unsupported_spot")
        self.assertIn("not installed", made.message)


class SpotLineTest(unittest.TestCase):
    def test_scenarios_become_action_lines(self):
        self.assertEqual(spot_events("UTG", None, None), ([], "first in"))
        self.assertEqual(spot_events("BTN", "UTG", "RFI"), ([("UTG", "pot")], "vs UTG open"))
        self.assertEqual(spot_events("UTG", "BTN", "3-Bet"), ([("UTG", "pot"), ("BTN", "pot")], "open, vs BTN 3-bet"))
        # "CO 3bet vs HJ" is the CO deciding against the HJ open.
        self.assertEqual(spot_events("CO", "HJ", "3-Bet")[0], [("HJ", "pot")])
        self.assertEqual(spot_events("HJ", "UTG", "4-Bet")[0], [("UTG", "pot"), ("HJ", "pot"), ("UTG", "pot")])
        self.assertEqual(spot_events("BB", "SB", "Limp")[0], [("SB", "call")])

    def test_unknown_seats_are_refused_not_crashed(self):
        with self.assertRaises(SpotError):
            spot_events("BTN", "LJ", "RFI")

    def test_impossible_lines_are_refused(self):
        with self.assertRaises(SpotError):
            spot_events("UTG", "BTN", "RFI")  # BTN cannot open before UTG acts
        with self.assertRaises(SpotError):
            spot_events("UTG", "UTG", "RFI")


@unittest.skipUnless(HAVE_CHARTS, "solved charts not exported (python -m plo_premium_proof export-chart)")
class SolvedChartTest(unittest.TestCase):
    def test_first_in_matches_the_published_range(self):
        made = plo_solved.answer("plo 40bb UTG AsKsQd9c", lang="EN")
        self.assertEqual(made.status, "solved_chart")
        self.assertIn("raise to 3.5bb 90%", made.message)
        self.assertIn("0.116bb ante", made.message)
        self.assertNotIn("to call", made.message)

    def test_facing_an_open_shows_the_price_and_the_line(self):
        made = plo_solved.answer("plo 40bb BTN vs UTG open 9876ds", lang="EN")
        self.assertIn("3.5bb to call", made.message)
        self.assertIn("UTG raise to 3.5", made.message)
        self.assertIn("raise to 12bb", made.message)

    def test_all_in_and_raise_caps(self):
        forty = plo_solved.answer("plo 40bb HJ facing 4bet from UTG AAKK ds", lang="EN").message
        self.assertIn("raise to 39.884bb (all-in)", forty)
        twenty = plo_solved.answer("plo 20bb HJ facing 4bet from UTG AAKK ds", lang="EN").message
        self.assertIn("call 20bb (all-in)", twenty)
        self.assertNotIn("raise", twenty.split("\n")[3])  # three raises is the 20bb cap

    def test_suit_shapes_and_three_flush_groups_resolve(self):
        made = plo_solved.answer("plo 20bb BTN AK74 ss AK7", lang="EN")
        self.assertIn("A♠K♠7♠4", made.message)

    def test_unsolved_depths_and_icm_go_elsewhere(self):
        self.assertEqual(plo_solved.answer("plo 30bb UTG AsKsQd9c", lang="EN").status, "unsupported_spot")
        self.assertIsNone(plo_solved.answer("PLO ICM 10bb BTN AK74 ss AK7", lang="EN"))
        self.assertIsNone(plo_solved.answer("plo 40bb UTG AsKsQd9c icm", lang="EN"))

    def test_thai_answer_and_followup_memory(self):
        th = plo_solved.answer("plo 40bb UTG AsKsQd9c", lang="TH")
        self.assertIn("raise ถึง 3.5bb", th.message)
        first = spot_chart.reply("plo 40bb UTG AsKsQd9c", lang="EN")
        moved = spot_chart.reply("BTN", memory=first.found.request, lang="EN")
        self.assertEqual(moved.kind, "plo_advice")
        self.assertIn("Spot: BTN, first in", moved.message)

    def test_other_table_seat_names_map_to_six_max(self):
        # LJ is UTG at 6-max: same seat, answered in the player's own name, no rename note.
        made = plo_solved.answer("plo 40bb BTN vs LJ open 9876ds", lang="EN")
        self.assertEqual(made.status, "solved_chart")
        self.assertIn("vs LJ open", made.message)
        self.assertIn("LJ raise to 3.5", made.message)
        self.assertNotIn("UTG", made.message)
        hero = plo_solved.answer("plo 40bb LJ AsKsQd9c", lang="EN")
        self.assertIn("Spot: LJ, first in", hero.message)
        utg = plo_solved.answer("plo 40bb UTG AsKsQd9c", lang="EN")
        self.assertEqual(hero.message.split("\n")[3], utg.message.split("\n")[3])
        same = plo_solved.answer("plo 40bb UTG vs LJ open AAKK ds", lang="EN")
        self.assertIn("same seat at 6-max", same.message)
        other = plo_solved.answer("plo 40bb CO vs UTG+1 open AAKK ds", lang="EN")
        self.assertIn("UTG+1 = HJ at 6-max", other.message)

    def test_followups_read_against_the_remembered_spot(self):
        def ask(text, memory):
            made = spot_chart.reply(text, memory=memory, lang="EN")
            return made, made.found.request
        first, memory = ask("plo 40bb UTG AsKsQd9c", None)
        made, memory = ask("what if BTN 3bets me?", memory)  # BTN is the opponent, hero stays UTG
        self.assertIn("Spot: UTG, open, vs BTN 3-bet", made.message)
        made, memory = ask("and with 9876ds instead?", memory)
        self.assertIn("Spot: UTG, open, vs BTN 3-bet", made.message)
        self.assertIn("9♠8♠7♥6♥", made.message)
        made, memory = ask("what about from the button?", memory)  # hero moves, back to first in
        self.assertIn("Spot: BTN, first in", made.message)
        made, memory = ask("ถ้า CO เปิดมาล่ะ", memory)
        self.assertIn("Spot: BTN, vs CO open", made.message)
        made, memory = ask("CO limps", memory)
        self.assertIn("Spot: BTN, vs CO limp", made.message)
        made, memory = ask("ถ้าอยู่ SB ล่ะ", memory)
        self.assertIn("Spot: SB, first in", made.message)

    def test_a_new_hand_without_suits_never_reuses_the_remembered_hand(self):
        memory = spot_chart.reply("plo 40bb UTG AhQhJhTc", lang="EN").found.request
        made = spot_chart.reply("9663 UTG first in", memory=memory, lang="EN")
        self.assertNotIn("A♥Q♥J♥T♣", made.message)
        self.assertIn("no suits given, assumed rainbow", made.message)
        rainbow = spot_chart.reply("9663 rainbow UTG", memory=memory, lang="EN")
        self.assertEqual(made.message.split("\n")[3], rainbow.message.split("\n")[3])
        letters = plo_solved.answer("plo 40bb AQJT UTG", lang="EN")
        self.assertIn("assumed rainbow", letters.message)
        vague = plo_solved.answer("plo 40bb A876 ss UTG", lang="EN")  # suited Ace or suited 87?
        self.assertEqual(vague.status, "by_suit_pattern")
        followup = spot_chart.reply("8854 vs HJ limp", memory=spot_chart.reply(
            "plo 40bb SB vs HJ limp TsTh5s2h", lang="EN").found.request, lang="EN")
        self.assertIn("Hand: 8♠8♥5♦4♣", followup.message)
        reused = spot_chart.reply("what about the button?", memory=memory, lang="EN")
        self.assertIn("(same hand as before)", reused.message)
        exact = spot_chart.reply("9663 ds", memory=memory, lang="EN")
        self.assertIn("Hand: 9♠6♠6♥3♥", exact.message)

    def test_ante_mismatch_is_noted(self):
        made = plo_solved.answer("plo 40bb UTG AsKsQd9c ante 0.1", lang="EN")
        self.assertIn("uses a 0.116bb ante, not 0.1bb", made.message)


if __name__ == "__main__":
    unittest.main()
