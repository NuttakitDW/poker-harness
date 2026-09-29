from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))

import assistant  # noqa: E402
import plo_advisor  # noqa: E402
import preflop  # noqa: E402
import spot_chart  # noqa: E402
from plo_icm.hand_advice import HandAdvice, WeightedValues  # noqa: E402


class AdvisorTest(unittest.TestCase):
    def setUp(self):
        result = HandAdvice(
            "raise_2bb", 2.0,
            WeightedValues("raise_2bb", {"fold": 120.0, "call": 121.0, "raise_2bb": 123.0},
                           {"fold": 1.25, "call": .75, "raise_2bb": 0.0}, 31.2),
            40, .2, {"completed_iterations": 9, "stop_reason": "time_limit"},
            {"fold": 0, "call": 1, "raise_2bb": 2})
        self.solver = mock.patch.object(plo_advisor, "solve_hand", return_value=result)
        self.solve = self.solver.start()
        self.addCleanup(self.solver.stop)

    def test_specific_hand_spot_returns_computed_approximation(self):
        advice = plo_advisor.advise("PLO ICM10bbBTN AK74 ss AK7", lang="EN")
        self.assertEqual(advice.status, "approximate_action")
        self.assertEqual(advice.hand.suiting.suited_ranks, ("A", "K", "7"))
        self.assertIn("Provisional model action: RAISE to 2bb", advice.message)
        self.assertIn("Unraised preflop choices are fold/limp/raise-to-2bb", advice.message)
        self.assertIn("Fold $120.00", advice.message)
        self.assertIn("Not GTO", advice.message)
        self.assertIn("76 remaining", advice.message)
        config = self.solve.call_args.args[0]
        self.assertEqual((config.stacks, config.players_remaining, config.ante),
                         ((10.0,) * 6, 76, .1))

    def test_nonselected_raise_ev_uses_its_own_actual_amount(self):
        result = HandAdvice(
            "call", 1.0,
            WeightedValues("call", {"fold": 120., "call": 123., "raise_2bb": 121.},
                           {"fold": 1., "call": 0., "raise_2bb": 1.}, 10.),
            12, .5, {}, {"fold": 0., "call": 1., "raise_2bb": 2.})
        self.solve.return_value = result
        advice = plo_advisor.advise("PLO ICM 10bb BTN AAKK ds", lang="EN")
        self.assertIn("Provisional model action: CALL to 1bb", advice.message)
        self.assertIn("Raise to 2bb $121.00", advice.message)

    def test_exact_cards_and_shorthand_are_equivalent(self):
        a = plo_advisor.advise("PLO BTN 10bb ICM AK74 ss AK7", lang="EN")
        b = plo_advisor.advise("PLO BTN 10bb ICM As Ks 7s 4d", lang="EN")
        self.assertEqual((a.hand.ranks, a.hand.suiting.suit_groups),
                         (b.hand.ranks, b.hand.suiting.suit_groups))

    def test_spaced_user_prompt_resolves_aakk_and_calls_real_advice_path(self):
        advice = plo_advisor.advise("plo icm 10bb btn AAKK ds", lang="EN")
        self.assertEqual(advice.status, "approximate_action")
        hand = self.solve.call_args.kwargs["hand"]
        self.assertEqual(set(hand), {"As", "Ah", "Ks", "Kh"})
        self.assertEqual(self.solve.call_args.kwargs["seat"], 3)

    def test_ambiguous_double_suited_pairing_requests_exact_cards(self):
        advice = plo_advisor.advise("plo icm 10bb btn AKQJ ds", lang="EN")
        self.assertEqual(advice.status, "ambiguous_hand")
        self.assertIn("exact suits", advice.message)
        self.solve.assert_not_called()

    def test_unsupported_table_and_vague_stage_never_reach_solver(self):
        for prompt in ("PLO ICM 5-handed BTN 10bb AAKK ds",
                       "PLO ICM final table BTN 10bb AAKK ds"):
            with self.subTest(prompt=prompt):
                advice = plo_advisor.advise(prompt, lang="EN")
                self.assertEqual(advice.status, "unsupported_spot")
        self.solve.assert_not_called()

    def test_remembered_custom_payouts_are_not_replaced_by_default_profile(self):
        memory = preflop.Request(game="plo", hero="BTN", stack=10, icm=True,
                                 players_left=6, payouts=(50, 30, 20), ante=.1,
                                 ante_mode="each", plo_hand="AAKK ds")
        advice = plo_advisor.advise("PLO ICM AAKK ds", memory=memory, lang="EN")
        self.assertEqual(advice.status, "approximate_action")
        self.assertEqual(self.solve.call_args.args[0].payouts, (50., 30., 20.))
        self.assertNotIn("Sunday Classic Mini assumptions", advice.message)

    def test_missing_hand_asks_for_four_cards_instead_of_a_chart(self):
        advice = plo_advisor.advise("PLO ICM10bbBTN", lang="EN")
        self.assertEqual(advice.status, "missing_hand")
        self.assertIn("exact four-card hand", advice.message)
        made = spot_chart.reply("PLO ICM10bbBTN", lang="EN")
        self.assertEqual(made.kind, "plo_advice")
        self.assertIsNotNone(made.found)

    def test_explicit_plo_icm_uses_confirmed_sunday_profile(self):
        generic = plo_advisor.advise("PLO ICM 10bb BTN AK74 ss AK7", lang="EN")
        sunday = plo_advisor.advise("PLO Sunday Classic Mini ICM 10bb BTN AK74 ss AK7", lang="EN")
        self.assertIn("76 remaining", generic.message)
        self.assertIn("76 remaining", sunday.message)
        self.assertIn("0.1bb individual ante", sunday.message)

    def test_generic_classifier_and_old_nlh_memory_are_unchanged(self):
        self.assertEqual(spot_chart.reply("PLO AAKK ds", lang="EN").kind, "plo_type")
        nlh = preflop.Request(game="tournament", hero="BTN", stack=10, icm=True)
        self.assertEqual(spot_chart.reply("AK74 ss AK7", memory=nlh, lang="EN").kind, "plo_type")

    def test_plo_context_routes_a_naked_hand_followup(self):
        first = spot_chart.reply("PLO ICM 10bb BTN", lang="EN")
        self.assertEqual((first.found.request.hero, first.found.request.stack, first.found.request.icm),
                         ("BTN", 10, True))
        followup = spot_chart.reply("AK74 ss AK7", memory=first.found.request, lang="EN")
        self.assertEqual(followup.kind, "plo_advice")
        self.assertEqual(followup.found.request.game, "plo")
        self.assertEqual(followup.found.request.hero, "BTN")
        self.assertEqual(followup.found.request.stack, 10)
        self.assertEqual(followup.found.request.icm, True)
        self.assertEqual(plo_advisor.advise("AK74 ss AK7", memory=first.found.request).hand.suiting.suited_ranks,
                         ("A", "K", "7"))

        changed = spot_chart.reply("8bb", memory=followup.found.request, lang="EN")
        self.assertEqual(changed.kind, "plo_advice")
        self.assertIn("Spot: BTN, 8bb", changed.message)
        self.assertIn("Resolved hand: As Ks 7s 4d", changed.message)

    def test_sunday_profile_survives_stage_and_ante_followups(self):
        first = spot_chart.reply("PLO Sunday Classic Mini ICM 10bb BTN AK74 ss AK7", lang="EN")
        moved = spot_chart.reply("60 left ante 0.2bb", memory=first.found.request, lang="EN")
        self.assertIn("60 remaining", moved.message)
        self.assertIn("outside field 54 × 10bb", moved.message)
        self.assertIn("0.2bb individual ante", moved.message)
        self.assertEqual(len(moved.found.request.payouts), 60)

    def test_chip_ev_memory_does_not_turn_into_sunday_icm(self):
        memory = preflop.Request(game="plo", hero="BTN", stack=10, payouts=(),
                                 plo_hand="AK74 ss AK7")
        made = spot_chart.reply("8bb", memory=memory, lang="EN")
        self.assertEqual(made.found.request.payouts, ())
        self.assertIn("provide an ordered payout", made.message)

    def test_generic_prompt_and_explicit_nlh_do_not_leak_plo_memory(self):
        memory = spot_chart.reply("PLO ICM 10bb BTN", lang="EN").found.request
        generic = spot_chart.reply("chart accuracy?", memory=memory, lang="EN")
        self.assertEqual(generic.kind, "plo_advice")
        self.assertEqual(generic.found.request.game, "plo")
        switched = spot_chart.reply("NLH BTN 10bb", memory=memory, lang="EN")
        self.assertNotEqual(switched.kind, "plo_advice")

    def test_facing_history_survives_a_stack_followup(self):
        first = spot_chart.reply("PLO BTN facing CO open 10bb AK74 ss AK7", lang="EN")
        self.assertEqual(first.found.request.villain, "CO")
        changed = spot_chart.reply("8bb", memory=first.found.request, lang="EN")
        self.assertNotIn("unopened pot assumed", changed.message)
        self.assertNotIn("pot raise to 3.5bb", changed.message)

    def test_unknown_facing_action_is_rejected_and_remembered(self):
        first = plo_advisor.advise("PLO ICM BTN 10bb AAKK ds facing a raise", lang="EN")
        self.assertEqual(first.status, "unsupported_spot")
        self.assertIsNotNone(first.request.unsupported_history)
        changed = plo_advisor.advise("8bb", memory=first.request, lang="EN")
        self.assertEqual(changed.status, "unsupported_spot")
        self.solve.assert_not_called()

    def test_ai_path_does_not_rewrite_or_invent_the_action(self):
        def must_not_run(*_args, **_kwargs):
            raise AssertionError("AI crafter should not run")

        made = assistant.answer("PLO ICM10bbBTN AK74 ss AK7", spot_chart.reply,
                                key="k", crafter=must_not_run)
        self.assertEqual(made.made.kind, "plo_advice")
        self.assertIn("Provisional model action", made.made.message)
        self.assertEqual(made.query, "PLO ICM10bbBTN AK74 ss AK7")

        memory = made.made.found.request
        changed = assistant.answer("8bb", spot_chart.reply, memory=memory,
                                   key="k", crafter=must_not_run)
        self.assertEqual(changed.made.kind, "plo_advice")
        self.assertIn("Spot: BTN, 8bb", changed.made.message)


if __name__ == "__main__":
    unittest.main()
