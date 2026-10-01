"""Checks for clustering PLO starting hands into Jeff Hwang's hand types and tiers."""

from pathlib import Path
import collections
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import plo_hand  # noqa: E402
import plo_type  # noqa: E402
import spot_chart  # noqa: E402

# คำตอบจากแบบฝึกที่ดัดแปลงจากหนังสือ ใช้เป็นชุดเฉลย ถ้าโค้ดจัดต่างจากนี้คือโค้ดผิด
DRILL_TIERS = {
    "K♠K♦Q♦J♠": "Premium", "J♦J♣6♣3♠": "Marginal", "A♠9♦8♦7♠": "Premium",
    "7♠6♣5♠5♣": "Speculative", "9♥7♦5♣3♠": "Trash", "A♠K♣Q♦9♠": "Premium",
    "A♠2♠9♣9♦": "Speculative", "K♦9♦6♣6♠": "Trash", "J♠T♣9♠8♣": "Premium",
    "A♠A♣8♦2♥": "Speculative", "K♦J♥T♦9♠": "Marginal", "Q♠J♠7♣6♣": "Trash",
    "A♠J♠T♦T♣": "Premium", "K♣Q♠J♠4♣": "Marginal", "A♦9♦8♠6♠": "Speculative",
    "A♠A♣J♠T♣": "Premium",
}


def tier(text: str) -> str:
    return plo_type.classify(plo_type.read(text)).tier


def group(text: str) -> str:
    return plo_type.classify(plo_type.read(text)).group


class ReadTests(unittest.TestCase):
    def test_explicit_suits_give_ranks_and_suits(self):
        hand = plo_type.read("plo As Ks Qd Jd")
        self.assertEqual(hand.ranks, "AKQJ")
        self.assertTrue(hand.suiting.double)
        self.assertTrue(hand.suiting.ace_suited)

    def test_suit_symbols_are_read(self):
        hand = plo_type.read("K♦9♦6♣6♠")
        self.assertEqual(hand.ranks, "K966")
        self.assertTrue(hand.suiting.suited)
        self.assertFalse(hand.suiting.ace_suited)

    def test_shape_word_sets_suiting(self):
        self.assertTrue(plo_type.read("AAKK ds").suiting.double)
        self.assertTrue(plo_type.read("AAKK double-suited").suiting.double)
        self.assertTrue(plo_type.read("AAKK ดับเบิลซูต").suiting.double)
        self.assertFalse(plo_type.read("JT98 rainbow").suiting.suited)
        self.assertFalse(plo_type.read("AK54 rb").suiting.suited)
        self.assertFalse(plo_type.read("AK54 RB").suiting.suited)
        self.assertFalse(plo_type.read("AK54 rb").suits_assumed)

    def test_missing_suits_are_read_as_assumed_rainbow(self):
        hand = plo_type.read("plo JT98")
        self.assertFalse(hand.suiting.suited)
        self.assertTrue(hand.suits_assumed)

    def test_numeric_hand_with_rb_is_a_plo_lookup(self):
        asked = plo_type.lookup("9753 rb")
        self.assertIsNotNone(asked)
        self.assertEqual(asked.hand.ranks, "9753")
        self.assertFalse(asked.hand.suiting.suited)

    def test_plain_single_suited_does_not_assume_the_ace(self):
        suiting = plo_type.read("AKQ9 ss").suiting
        self.assertIsNone(suiting.ace_suited)
        self.assertEqual(suiting.suited_ranks, ())

    def test_ordinary_words_do_not_look_like_exact_suited_cards(self):
        hand = plo_type.read("please classify A234 ss A2")
        self.assertEqual(hand.ranks, "A432")
        self.assertEqual(hand.suiting.suited_ranks, ("A", "2"))

    def test_single_suited_pair_identifies_whether_ace_is_suited(self):
        with_ace = plo_type.read("A234 ss A2").suiting
        without_ace = plo_type.read("A234 ss23").suiting
        self.assertEqual((with_ace.ace_suited, with_ace.suited_ranks), (True, ("A", "2")))
        self.assertEqual((without_ace.ace_suited, without_ace.suited_ranks), (False, ("2", "3")))

    def test_single_suited_suffix_preserves_the_full_suit_group(self):
        shorthand = plo_type.read("PLO AK74 ss AK7")
        exact = plo_type.read("PLO As Ks 7s 4d")
        self.assertEqual(shorthand.suiting.suited_ranks, ("A", "K", "7"))
        self.assertEqual(shorthand.suiting.suit_groups, exact.suiting.suit_groups)
        self.assertTrue(shorthand.suiting.ace_suited)

    def test_bad_single_suited_suffix_is_not_silently_truncated(self):
        for text in ("PLO AK74 ss AK77", "PLO AK74 ss AK7X", "PLO AK74 ss A5"):
            with self.subTest(text=text), self.assertRaises(plo_type.PloParseError):
                plo_type.read(text)

    def test_explicit_cards_are_authoritative_over_shape_words(self):
        hand = plo_type.read("plo As 2s 3d 4c rainbow")
        self.assertTrue(hand.suiting.suited)
        self.assertTrue(hand.suiting.ace_suited)

    def test_exact_suit_groups_choose_an_ace_with_a_real_partner(self):
        for text, pair in (("As Ah Kh Qd", "AK"), ("As Ah Ks Kh", "AK"),
                           ("As Ks 9s 5s", "AK")):
            with self.subTest(text=text):
                hand = plo_type.read(text)
                group, _ = plo_type._ace_suit_group(hand)
                self.assertIn("A", group)
                self.assertIn(pair[1], group)
                self.assertNotEqual(group[:2], ("A", "A"))

    def test_invalid_multiplicity_pair_and_contradictions_are_helpful(self):
        cases = {
            "plo As As Kd Qc": "same physical card",
            "plo As Ks Qd": "exactly four physical cards",
            "plo As Ks Qd Jd 9c": "exactly four physical cards",
            "plo AAAAA ss": "exactly four",
            "plo AAKK ss AA": "cannot be the same physical suit",
            "plo A234 ss KQ": "not in",
            "plo A234 ds rainbow": "contradict",
            "plo AK54 rb ss": "contradict",
        }
        for text, phrase in cases.items():
            with self.subTest(text=text):
                answer = plo_type.answer(plo_type.lookup(text), "EN")
                self.assertIn("Invalid PLO hand", answer)
                self.assertIn(phrase, answer)

    def test_push_fold_questions_are_not_plo(self):
        for text in ("BB vs BTN shove 10bb", "BTN shove 10bb hold K5s", "aof BB vs CO",
                     "UTG all-in, BTN call, I'm in the SB 5bb", "เหลือ 120 คน BTN 8bb"):
            self.assertIsNone(plo_type.lookup(text), text)

    def test_four_rank_word_or_keyword_is_plo(self):
        self.assertIsNotNone(plo_type.lookup("AAKK ds"))
        self.assertIsNotNone(plo_type.lookup("plo แจ็ค แจ็ค 6 3"))
        self.assertIsNotNone(plo_type.lookup("omaha hand types"))


class DrillTests(unittest.TestCase):
    def test_every_drill_answer_matches(self):
        for cards, want in DRILL_TIERS.items():
            self.assertEqual(tier(cards), want, cards)

    def test_drill_file_answers_match(self):
        # แบบฝึกที่เพิ่มทีหลังต้องผ่านด้วย ไม่ใช่แค่ชุดที่เขียนไว้ในเทสต์
        for item in plo_hand._drills():
            got = plo_type.classify(plo_type.from_shape(item.hand, item.shape, ace_suited=True))
            self.assertEqual(got.tier, item.tier, f"{item.hand} {item.shape}")


class HwangExampleTests(unittest.TestCase):
    """ตัวอย่างที่หนังสือบอกระดับหรือกลุ่มไว้ตรง ๆ บทที่ 4"""

    def test_big_cards_and_broadway_wrap(self):
        self.assertEqual(group("KQJT ss"), "big_cards")
        self.assertEqual(tier("KQJT ss"), "Premium")
        self.assertEqual(tier("KQJT rainbow"), "Marginal")
        self.assertEqual(group("AJT9 ss AJ"), "broadway_wrap")
        self.assertEqual(tier("AJT9 ss AJ"), "Premium")

    def test_rundown_forms(self):
        cases = {"JT98": "Premium", "6543": "Premium", "5432": "Trash", "QJT8": "Premium",
                 "QJ98": "Premium", "QJ97": "Speculative", "QJT7": "Speculative",
                 "QJ87": "Speculative", "J987": "Marginal", "J986": "Marginal",
                 "J976": "Trash", "KT98": "Marginal", "J876": "Trash"}
        for hand, want in cases.items():
            self.assertEqual(tier(f"{hand} ss"), want, hand)

    def test_unsuited_rundown_is_marginal(self):
        self.assertEqual(tier("JT98 rainbow"), "Marginal")
        self.assertEqual(tier("QJT7 rainbow"), "Trash")

    def test_suited_ace_hands(self):
        cases = {"A654": "Premium", "A875": "Speculative", "A874": "Speculative",
                 "A864": "Marginal", "A854": "Marginal", "AKQ5": "Speculative",
                 "AK72": "Marginal", "A932": "Trash", "A543": "Marginal"}
        for hand, want in cases.items():
            named = f"{hand} ss A{next(rank for rank in hand if rank != 'A')}"
            self.assertEqual(tier(named), want, hand)
            self.assertEqual(group(named), "suited_ace", hand)

    def test_pair_plus_hands(self):
        cases = {"QQJJ": "Premium", "8877": "Speculative", "KK33": "Speculative",
                 "4433": "Trash", "9987": "Speculative", "JJ63": "Marginal"}
        for hand, want in cases.items():
            self.assertEqual(tier(f"{hand} ss"), want, hand)
            self.assertEqual(group(f"{hand} ss"), "pair_plus", hand)

    def test_aces(self):
        self.assertEqual(tier("AA82 rainbow"), "Speculative")
        self.assertEqual(tier("AA87 ss A8"), "Premium")
        self.assertEqual(tier("AA93 ds"), "Premium")
        self.assertFalse(plo_type.classify(plo_type.read("AA93 ds")).magnum)
        self.assertTrue(plo_type.classify(plo_type.read("AAKK ds")).magnum)
        self.assertEqual(group("AAKK ds"), "aces")

    def test_trips_are_trash(self):
        self.assertEqual(tier("AAA5 ds"), "Trash")


class RenderTests(unittest.TestCase):
    def test_hand_shows_group_tier_and_source(self):
        text = plo_type.render(plo_type.read("KKQJ ds"), "EN")
        self.assertIn("Pair-Plus", text)
        self.assertIn("Premium", text)
        self.assertIn("Hwang", text)

    def test_plain_ss_ace_shows_a_short_conditional(self):
        text = plo_type.render(plo_type.read("plo A654 ss"), "EN")
        self.assertIn("if Ace shares the suit", text)
        self.assertIn("specify it like ss A2", text)
        self.assertNotIn("Assumes", text)
        self.assertLessEqual(max(map(len, text.splitlines())), 64)

    def test_output_removes_cluster_and_by_suits(self):
        text = plo_type.render(plo_type.read("plo JT98 ss"), "EN")
        self.assertNotIn("Cluster", text)
        self.assertNotIn("By suits", text)

    def test_plain_answer_leads_with_tier_and_how_to_play(self):
        text = plo_type.render(plo_type.read("plo JT98 ds"), "EN")
        self.assertLess(text.index("Tier"), text.index("How to play"))
        self.assertLess(text.index("How to play"), text.index("Type"))
        self.assertIn("value raise", text)
        self.assertIn("authored", text)

    def test_each_tier_has_bounded_general_play_guidance(self):
        cases = {
            "JT98 ds": "value raise",
            "QJ97 ds": "See a flop cheaply",
            "J987 ss": "late position",
            "9753 ss": "Usually fold",
        }
        for hand, phrase in cases.items():
            with self.subTest(hand=hand):
                text = plo_type.render(plo_type.read(hand), "EN")
                self.assertIn(phrase, " ".join(text.split()))
                self.assertNotIn("always reraise", text.lower())

    def test_unidentified_suited_pair_does_not_get_a_definitive_play_line(self):
        conditional = plo_type.render(plo_type.read("A654 ss"), "EN")
        self.assertIn("specify it like ss A2", " ".join(conditional.split()))

    def test_play_includes_a_group_specific_postflop_plan(self):
        cases = {"JT98 ds": "nut straight, 13+ out wraps", "AAKK ds": "unimproved Aces",
                 "KKQJ ds": "set mining", "plo As Kd 8s 6c": "nut flush draw plus a wrap",
                 "A876 rb": "no nut flush draw", "QJ76 rb": "only the nuts continues"}
        for hand, phrase in cases.items():
            with self.subTest(hand=hand):
                payload = plo_type.presentation(plo_type.read(hand), "EN")
                self.assertIn("After the flop:", payload["play"])
                self.assertIn(phrase, payload["play"])

    def test_ak54_rb_is_the_same_direct_trash_answer_as_rainbow(self):
        short = plo_type.read("plo AK54 rb")
        written = plo_type.read("plo AK54 rainbow")
        self.assertEqual(short, written)
        for lang, fold in (("EN", "Usually fold"), ("TH", "ส่วนใหญ่ fold")):
            with self.subTest(lang=lang):
                for text in (plo_type.render(short, lang),
                             plo_type.terminal(short, lang, color=False, width=60)):
                    flat = " ".join(text.split())
                    self.assertIn("Trash", flat)
                    self.assertIn(fold, flat)
                    self.assertNotIn("suits not given", flat)
                    self.assertNotIn("ไม่ได้บอกดอก", flat)
                    self.assertNotIn("exact suits", flat)
                    self.assertNotIn("บอกดอกที่แท้จริง", flat)

    def test_t885_is_trash_without_needing_suits(self):
        for lang, fold in (("EN", "Usually fold"), ("TH", "ส่วนใหญ่ fold")):
            with self.subTest(lang=lang):
                hand = plo_type.read("plo T885")
                for text in (plo_type.render(hand, lang),
                             plo_type.terminal(hand, lang, color=False, width=60)):
                    flat = " ".join(text.split())
                    self.assertIn("Trash", flat)
                    self.assertIn(fold, flat)
                    self.assertNotIn("exact suits", flat)
                    self.assertNotIn("nut-flush", flat)
                    self.assertNotIn("nut flush draw", flat)

    def test_t885_stays_trash_when_suits_are_known(self):
        for description in ("T885 ss85", "T885 ds"):
            with self.subTest(description=description):
                text = plo_type.render(plo_type.read(description), "EN")
                self.assertIn("Tier      Trash", text)
                self.assertIn("Usually fold", " ".join(text.split()))

    def test_other_structural_trash_hands_do_not_need_suits(self):
        for ranks in ("QJ76", "K966"):
            with self.subTest(ranks=ranks):
                text = plo_type.render(plo_type.read(ranks), "EN")
                self.assertIn("Tier      Trash", text)
                self.assertNotIn("depends on the exact suits", text)
                self.assertNotIn("Give the exact suits", text)

    def test_missing_suits_are_classified_as_rainbow(self):
        for ranks, tier in (("A234", "Trash"), ("JT98", "Marginal"), ("AKQJ", "Marginal")):
            with self.subTest(ranks=ranks):
                hand = plo_type.read(f"plo {ranks}")
                text = plo_type.render(hand, "EN")
                self.assertEqual(plo_type.classify(hand), plo_type.classify(plo_type.read(f"{ranks} rb")))
                self.assertIn(f"Tier      {tier}", text)
                self.assertIn("rainbow (no suits given, assumed)", text)
                self.assertNotIn("exact suits", text)
                self.assertNotIn("Suited Ace", text)
        thai = plo_type.render(plo_type.read("plo JT98"), "TH")
        self.assertIn("ไม่ได้บอกดอก ถือว่า rainbow", thai)

    def test_known_non_ace_pair_has_neutral_type_and_no_nut_flush_claim(self):
        text = plo_type.render(plo_type.read("plo A654 ss65"), "EN")
        self.assertIn("Ace-high connected hand", text)
        self.assertIn("not the nut flush draw", " ".join(text.split()))
        self.assertNotIn("Type      Suited Ace Hands", text)

    def test_miracle_flop_is_a_verified_rank_nut_without_percentages(self):
        hand = plo_type.read("plo A234 ss23")
        text = plo_type.render(hand, "EN")
        self.assertIn("4♦ 3♠ + 6♠ 5♥ 2♦ rainbow → nut straight", " ".join(text.split()))
        self.assertNotRegex(text, r"\d+(?:\.\d+)?%")
        hole = tuple(plo_hand.VALUE[rank] for rank in hand.ranks)
        board = tuple(plo_hand.VALUE[rank] for rank in "652")
        unseen = collections.Counter({value: plo_hand.DECK_COPIES for value in plo_hand.VALUE.values()})
        unseen.subtract(hole)
        unseen.subtract(board)
        score, pair = plo_hand._best(hole, board)
        self.assertEqual(score, plo_hand._nuts(board, unseen))
        self.assertEqual(set(pair), {plo_hand.VALUE["4"], plo_hand.VALUE["3"]})

    def test_known_suited_ace_gets_a_literal_five_card_flush_illustration(self):
        text = plo_type.render(plo_type.read("plo As 2s 3d 4c"), "EN")
        self.assertIn("A♠ 2♠ + K♠ 9♠ 5♠ → nut flush", " ".join(text.split()))

    def test_flush_illustration_never_reuses_a_held_card(self):
        for cards in ("As Ah Kh Qd", "As Ks 9s 5s", "As Ah Ks Kh", "As Ks 5s Qd"):
            with self.subTest(cards=cards):
                hand = plo_type.read(cards)
                miracle = plo_type._miracle(hand, "EN").split("\n")[0]
                shown = plo_type._ONE_CARD.findall(miracle)
                self.assertEqual(len(shown), len(set(shown)))
                board = frozenset(plo_hand.VALUE[rank] for rank, _ in shown[-3:])
                self.assertFalse(any(board <= window for window in plo_hand.STRAIGHT_WINDOWS))

    def test_miracle_flops_list_several_verified_nut_flops(self):
        for ranks in ("JT98", "KKQJ", "AAKK", "QJ76"):
            with self.subTest(ranks=ranks):
                hand = plo_type.read(f"plo {ranks}")
                lines = plo_type._miracle(hand, "EN").split("\n")
                self.assertGreaterEqual(len(lines), 3)
                self.assertLessEqual(len(lines), plo_type.MIRACLE_MAX)
                self.assertEqual(len(lines), len(set(lines)))
                hole = tuple(plo_hand.VALUE[rank] for rank in hand.ranks)
                for line in lines:
                    holes, board = line.split(" rainbow")[0].split(" + ")
                    board_values = tuple(plo_hand.VALUE[rank] for rank in board.split("-"))
                    unseen = collections.Counter({value: plo_hand.DECK_COPIES
                                                  for value in plo_hand.VALUE.values()})
                    unseen.subtract(hole)
                    unseen.subtract(board_values)
                    score, pair = plo_hand._best(hole, board_values)
                    self.assertGreaterEqual(score, plo_hand._nuts(board_values, unseen), line)
                    self.assertEqual(plo_hand._label(pair), holes, line)

    def test_miracle_flops_skip_trips_boards_when_real_flops_exist(self):
        text = plo_type._miracle(plo_type.read("plo AKQJ"), "EN")
        self.assertNotIn("A-A-A", text)
        self.assertNotIn("full house", text)

    def test_pocket_pairs_list_quads_and_nut_full_house_flops(self):
        text = plo_type._miracle(plo_type.read("plo 6633"), "EN")
        self.assertIn("6-6 + A-6-6 rainbow → quads", text)
        self.assertIn("3-3 + A-3-3 rainbow → quads", text)
        self.assertIn("K-K + K-7-7 rainbow → nut full house",
                      plo_type._miracle(plo_type.read("plo KK72"), "EN"))

    def test_shape_only_hands_show_example_suits_on_cards_and_flops(self):
        payload = plo_type.presentation(plo_type.read("plo AAKK ds"), "EN")
        self.assertEqual([card["rank"] + card["suit"] for card in payload["cards"]],
                         ["A♠", "A♥", "K♠", "K♥"])
        self.assertIn("suits shown are an example", payload["title"])
        lines = payload["miracle"].split("\n")
        self.assertEqual(lines[0], "A♠ K♠ + Q♠ 9♠ 5♠ → nut flush")
        self.assertIn("A♠ K♠ + Q♠ J♥ T♦ rainbow → nut straight", lines)
        rainbow = plo_type.presentation(plo_type.read("plo 6633"), "EN")
        self.assertEqual(len({card["suit"] for card in rainbow["cards"]}), 4)
        self.assertIn("6♠ 6♥ + A♠ 6♦ 6♣ rainbow → quads", rainbow["miracle"])

    def test_exact_cards_are_not_labelled_as_an_example(self):
        payload = plo_type.presentation(plo_type.read("plo As Ks Qd Jd"), "EN")
        self.assertNotIn("example", payload["title"])

    def test_ambiguous_single_suited_ace_keeps_rank_only_cards(self):
        payload = plo_type.presentation(plo_type.read("plo A654 ss"), "EN")
        self.assertEqual({card["suit"] for card in payload["cards"]}, {""})

    def test_suited_ace_miracle_list_starts_with_the_nut_flush(self):
        lines = plo_type._miracle(plo_type.read("plo As Ks Qd Jd"), "EN").split("\n")
        self.assertTrue(lines[0].endswith("nut flush"))
        self.assertTrue(any("nut straight" in line for line in lines[1:]))

    def test_terminal_is_spacious_wrapped_and_ansi_is_optional(self):
        hand = plo_type.read("plo A654 ss")
        plain = plo_type.terminal(hand, "EN", color=False, width=60)
        coloured = plo_type.terminal(hand, "EN", color=True, width=60)
        self.assertIn("┌─────┐  ┌─────┐", plain)
        self.assertIn("│  A  │  │  6  │", plain)
        self.assertIn("TYPE", plain)
        self.assertIn("TIER", plain)
        self.assertIn("╔", plain)
        self.assertIn("PREMIUM", plain.upper())
        self.assertLess(plain.index("TIER"), plain.index("HOW TO PLAY"))
        self.assertLess(plain.index("HOW TO PLAY"), plain.index("TYPE"))
        self.assertNotRegex(plain, r"\x1b\[")
        self.assertRegex(coloured, r"\x1b\[")
        self.assertLessEqual(max(map(len, plain.splitlines())), 60)

    def test_overview_lists_every_group(self):
        text = plo_type.overview("EN")
        for name in ("Big Cards", "Broadway Wrap", "Straight", "Suited Ace", "Pair-Plus",
                     "Aces", "Marginal"):
            self.assertIn(name, text)

    def test_thai_render(self):
        self.assertIn("ระดับ", plo_type.render(plo_type.read("plo แจ็ค แจ็ค 6 3"), "TH"))


class SpotChartTests(unittest.TestCase):
    def test_reply_routes_plo_hands(self):
        made = spot_chart.reply("AAKK ds")
        self.assertEqual(made.kind, "plo_type")
        self.assertIn("Aces", made.message)
        self.assertNotRegex(made.message, r"\x1b\[")

    def test_terminal_answer_uses_card_tiles(self):
        shown, _ = spot_chart.answer("plo A234 ss A2", color=False)
        self.assertIn("│  A  │", shown)
        self.assertIn("MIRACLE FLOP", shown.upper())

    def test_reply_still_solves_push_fold(self):
        self.assertEqual(spot_chart.reply("BTN shove 10bb tournament").kind, "chart")


if __name__ == "__main__":
    unittest.main()
