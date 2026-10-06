from pathlib import Path
import math
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))

import chart_grid  # noqa: E402
import assistant  # noqa: E402
import icm_chart  # noqa: E402
import preflop  # noqa: E402
import spot  # noqa: E402
import spot_chart  # noqa: E402


class IcmParsingTests(unittest.TestCase):
    def test_open_query_keeps_effective_stack(self):
        request = preflop.parse("3 handed BTN open 15bb icm 50/30/20 no ante")
        self.assertEqual((request.hero, request.stack, request.open_size), ("BTN", 15, None))

    def test_action_size_is_not_the_effective_stack_in_either_order(self):
        for text in ("BB vs BTN open 2.5bb 20bb icm 50/30/20",
                     "20bb BB vs BTN open 2.5bb icm 50/30/20"):
            with self.subTest(text=text):
                request = preflop.parse(text)
                self.assertEqual((request.stack, request.open_size), (20, 2.5))

    def test_open_to_without_a_stack_does_not_invent_one(self):
        request = preflop.parse("BTN open to 2.5bb icm 50/30/20")
        self.assertIsNone(request.stack)
        self.assertEqual(request.open_size, 2.5)

    def test_facing_threebet_preserves_the_opener_as_hero(self):
        request = preflop.parse("3 handed BTN open facing BB 3bet 15bb icm 50/30/20")
        self.assertEqual((request.hero, request.villain, request.scenario),
                         ("BTN", "BB", "3-Bet"))

    def test_explicit_hero_marker_wins_in_full_threebet_history(self):
        request = preflop.parse("3 handed BTN opened and BB 3bet to 6.6bb, hero BTN 20bb "
                                "icm 50/30/20 no ante")
        self.assertEqual((request.hero, request.villain, request.scenario, request.stack,
                          request.threebet_size), ("BTN", "BB", "3-Bet", 20, 6.6))

    def test_size_before_open_is_not_read_as_stack(self):
        request = preflop.parse("3 handed BB vs BTN 2.5bb open 20bb icm 50/30/20 no ante")
        self.assertEqual((request.stack, request.open_size), (20, 2.5))

    def test_explicit_pushfold_is_distinct_from_a_shove_event(self):
        self.assertTrue(preflop.parse("BTN push/fold 10bb icm 50/30/20").explicit_pushfold)
        self.assertFalse(preflop.parse("BB vs BTN shove 10bb icm 50/30/20").explicit_pushfold)


class IcmValidationTests(unittest.TestCase):
    def test_unequal_named_stacks_are_rejected(self):
        request = preflop.parse("BTN 20bb SB 10bb BB 5bb icm 50/30/20")
        self.assertIn("unequal stacks", icm_chart.problem(request))

    def test_postflop_and_flat_requests_are_rejected(self):
        for text in ("3 handed BTN flop 15bb icm 50/30/20",
                     "3 handed BTN board As Kd 7h 15bb icm 50/30/20",
                     "3 handed BB call open BTN 15bb icm 50/30/20",
                     "3 handed BB vs BTN open and SB call 20bb icm 50/30/20"):
            with self.subTest(text=text):
                self.assertIsNotNone(icm_chart.problem(preflop.parse(text)))

    def test_illegal_explicit_raise_sizes_are_rejected(self):
        for text in ("3 handed BTN open 1.5bb 20bb icm 50/30/20",
                     "3 handed BB vs BTN open 2.2bb 3bet to 3bb 20bb icm 50/30/20"):
            with self.subTest(text=text):
                self.assertIsNotNone(icm_chart.problem(preflop.parse(text)))

    def test_chip_ev_clears_remembered_icm_stage(self):
        request = preflop.Request(stack=15, hero="BTN", scenario="RFI", payouts=(),
                                  stage_word="bubble", icm=True)
        self.assertFalse(icm_chart.applies(request))

    def test_a_short_stack_at_a_full_table_goes_to_push_fold(self):
        short = preflop.parse("8 handed SB 9.8bb hold A2s 240 paid 243 left bubble อีก 3 คน shove ได้ไหม")
        self.assertFalse(icm_chart.applies(short))
        self.assertTrue(icm_chart.applies(preflop.parse("8 handed BTN 20bb bubble")))
        self.assertTrue(icm_chart.applies(preflop.parse("8 handed BB vs CO open 12bb bubble")))
        self.assertTrue(icm_chart.applies(preflop.parse("3 handed BTN 10bb icm 50/30/20")))

    def test_new_global_stack_clears_old_named_stacks(self):
        old = preflop.parse("BTN 15bb SB 15bb BB 15bb icm 50/30/20")
        changed = spot.merge(preflop.parse("12bb"), old)
        self.assertEqual(changed.stack, 12)
        self.assertEqual(changed.seat_stacks, ())

    def test_default_sizes_may_clip_at_short_stacks(self):
        request = preflop.parse("3 handed BTN open 3bb icm 50/30/20 no ante")
        self.assertIsNone(icm_chart.problem(request))

    def test_budget_configuration_is_bounded(self):
        self.assertEqual(icm_chart.solve_seconds({"VERCEL": "1"}), 25)
        self.assertEqual(icm_chart.solve_seconds({"ICM_SOLVE_SECONDS": "400"}), 240)
        self.assertEqual(icm_chart.solve_seconds({"ICM_SOLVE_SECONDS": "bad"}), 180)


class IcmLiveSolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        icm_chart._solve.cache_clear()
        cls.opened = spot_chart.reply("3 handed BTN open 15bb icm 50/30/20 no ante")
        cls.facing = spot_chart.reply("3 handed BB vs BTN open 15bb icm 50/30/20 no ante")

    def test_open_chart_has_distinct_open_and_allin_probabilities(self):
        chart = self.opened.found.chart
        self.assertEqual(chart["names"]["raise"], "open 2.2")
        self.assertEqual(chart["names"]["allin"], "all-in")
        self.assertEqual(set(chart["mixed"]["AKs"]), {"fold", "raise", "allin"})
        self.assertTrue(math.isclose(sum(chart["mixed"]["AKs"].values()), 1.0))

    def test_facing_open_selects_a_raise_history(self):
        chart = self.facing.found.chart
        self.assertEqual((chart["hero"], chart["villain"]), ("BB", "BTN"))
        self.assertEqual(chart["names"]["raise"], "3bet 6.6")
        self.assertNotIn("call", chart["names"])

    def test_every_hand_has_finite_normalized_frequencies(self):
        for shares in self.opened.found.chart["mixed"].values():
            self.assertTrue(all(math.isfinite(value) and value >= 0 for value in shares.values()))
            self.assertTrue(math.isclose(sum(shares.values()), 1.0, abs_tol=1e-6))

    def test_renderer_exposes_every_engine_action(self):
        entries = dict(chart_grid.legend_entries(self.opened.found.chart, "EN"))
        self.assertIn("R", entries)
        self.assertIn("J", entries)
        self.assertIn("F", entries)

    def test_live_route_does_not_depend_on_static_books(self):
        with mock.patch.object(preflop, "books", return_value=()):
            made = spot_chart.reply("3 handed BTN open 15bb icm 50/30/20 no ante")
        self.assertEqual(made.kind, "chart")
        self.assertEqual(made.found.chart["hero"], "BTN")

    def test_smalltalk_does_not_repeat_the_remembered_solve(self):
        with mock.patch.object(icm_chart, "solved", side_effect=AssertionError("must not solve")):
            made = spot_chart.reply("thanks", memory=self.opened.found.request)
        self.assertEqual(made.kind, "not_found")

    def test_facing_threebet_does_not_label_hero_as_the_opponent(self):
        made = spot_chart.reply("3 handed BTN open facing BB 3bet 15bb icm 50/30/20 no ante")
        self.assertEqual((made.found.chart["hero"], made.found.chart["villain"]), ("BTN", "BB"))


class AssistantFallbackTests(unittest.TestCase):
    def test_null_query_calls_solver_once(self):
        reply = mock.Mock(return_value=type("Reply", (), {"kind": "not_found"})())
        crafted = lambda *_args: assistant.Crafted("need more", None)
        assistant.answer("hello", reply, key="key", crafter=crafted)
        reply.assert_not_called()

    def test_method_question_does_not_redraw_remembered_chart(self):
        reply = mock.Mock(return_value=type("Reply", (), {"kind": "chart"})())
        crafted = lambda *_args: assistant.Crafted("method answer", None)
        memory = preflop.Request(hero="BTN", stack=15, scenario="RFI", payouts=(50, 30, 20))
        made = assistant.answer("How accurate are these charts?", reply, memory=memory,
                                key="key", crafter=crafted)
        reply.assert_not_called()
        self.assertEqual(made.say, "method answer")

    def test_standalone_spot_fallback_calls_solver_once(self):
        reply = mock.Mock(return_value=type("Reply", (), {"kind": "chart"})())
        crafted = lambda *_args: assistant.Crafted("need more", None)
        assistant.answer("BTN 15bb", reply, key="key", crafter=crafted)
        reply.assert_called_once()


if __name__ == "__main__":
    unittest.main()
