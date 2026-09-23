"""Checks for routing a spoken question to the right topic card."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import corpus  # noqa: E402
import retrieval  # noqa: E402
import brain  # noqa: E402


class CorpusTests(unittest.TestCase):
    def test_both_language_editions_load(self):
        languages = {card.language for card in corpus.load_cards()}
        self.assertEqual(languages, {"TH", "EN"})

    def test_general_poker_cards_have_both_language_editions(self):
        cards = corpus.load_cards()
        for slug in ("22-poker-players-and-thailand", "23-poker-tours-and-history", "24-poker-rankings-and-results"):
            with self.subTest(slug=slug):
                self.assertEqual({card.language for card in cards if card.slug == slug}, {"TH", "EN"})

    def test_cards_resolve_real_source_pages(self):
        cards = [c for c in corpus.load_cards() if c.citations]
        self.assertTrue(cards)
        for citation in cards[0].citations:
            self.assertTrue(citation.path.exists())

    def test_page_extraction_returns_only_that_page(self):
        card = next(c for c in corpus.load_cards() if any(x.page for x in c.citations))
        citation = next(x for x in card.citations if x.page)
        page = corpus.read_page(citation)
        self.assertIn(f"## PDF page {citation.page}", page)
        self.assertEqual(page.count("## PDF page "), 1)


class RoutingTests(unittest.TestCase):
    def assert_routes_to(self, question: str, prefix: str) -> None:
        hits = retrieval.search(question)
        self.assertTrue(hits, f"ไม่พบการ์ดสำหรับ: {question}")
        self.assertTrue(hits[0].card.slug.startswith(prefix),
                        f"{question} -> {hits[0].card.slug}")

    def test_icm_question_routes_to_tournament_card(self):
        self.assert_routes_to("ICM ตอน bubble ทำให้ range ที่ shove แคบลงแค่ไหน", "13")

    def test_bankroll_question_routes_to_mental_game_card(self):
        self.assert_routes_to("bankroll ควรมีกี่ buy-in สำหรับ micro stakes", "19")

    def test_cbet_question_routes_to_flop_texture_card(self):
        self.assert_routes_to("เจอ c-bet บน flop แห้ง ควร check-raise ด้วย range ไหน", "07")

    def test_language_filter_restricts_results(self):
        hits = retrieval.search("pot odds และ equity", language="EN")
        self.assertTrue(all(hit.card.language == "EN" for hit in hits))

    def test_unrelated_question_returns_nothing(self):
        self.assertEqual(retrieval.search("zzzz qqqq xxxx"), ())

    def test_general_poker_people_tours_and_rankings_route_to_new_cards(self):
        for question, prefix in (
            ("ลูกชุปรู้จักพิปป๊อปนาทีนักโป๊กเกินดับหนึ่งในประเทศไทยไหมครับ", "24"),
            ("รู้จักปุณณัตถ์ ปุณศรีไหม", "22"),
            ("Phil Ivey คือใคร", "22"),
            ("รู้จักฟิล ไอวี่ไหม", "22"),
            ("แดเนียล เนเกรนูคือใคร", "22"),
            ("EPT คืออะไร", "23"),
            ("Triton คืออะไร", "23"),
            ("ไทรทันคืออะไร", "23"),
            ("เวิลด์โป๊กเกอร์ทัวร์คืออะไร", "23"),
            ("เวิลด์ซีรีส์ออฟโป๊กเกอร์คืออะไร", "23"),
            ("GPI Player of the Year ต่างจาก all-time money list อย่างไร", "24"),
        ):
            with self.subTest(question=question):
                self.assert_routes_to(question, prefix)

    def test_general_knowledge_context_includes_relevant_dated_evidence(self):
        for question, evidence in (
            ("ลูกชุปรู้จักพิปป๊อปนาทีนักโป๊กเกินดับหนึ่งในประเทศไทยไหมครับ", "Ranking snapshot: Generated 2026-09-20"),
            ("รู้จักปุณณัตถ์ ปุณศรีไหม", "Tatler Asia Thai-language interview"),
            ("Phil Ivey คือใคร", "2017 Poker Hall of Fame"),
            ("รู้จักฟิล ไอวี่ไหม", "2017 Poker Hall of Fame"),
            ("แดเนียล เนเกรนูคือใคร", "2014 Poker Hall of Fame"),
            ("Kannapong Tent คือใคร", "Natural8 official announcement"),
            ("Triton คืออะไร", "Triton Poker Series official story page"),
            ("ไทรทันคืออะไร", "Triton Poker Series official story page"),
            ("เวิลด์โป๊กเกอร์ทัวร์คืออะไร", "World Poker Tour official about page"),
            ("เวิลด์ซีรีส์ออฟโป๊กเกอร์คืออะไร", "World Series of Poker official news"),
        ):
            with self.subTest(question=question):
                context, topics, pages = brain.gather(question)
                self.assertIn(evidence, context)
                self.assertTrue(topics)
                self.assertTrue(pages)

    def test_ambiguous_name_context_asks_to_identify_person(self):
        context, topics, _ = brain.gather("พิปป๊อปนาทีคือใคร")
        self.assertIn("TH/22-poker-players-and-thailand", topics)
        self.assertIn("ถ้าชื่อจากเสียงไม่ชัด", context)
        self.assertIn("ถามชื่อซ้ำสั้น ๆ", context)
        self.assertIn("ชื่อคนจากเสียงอาจเพี้ยน", brain.system_prompt())

    def test_english_general_knowledge_routes_to_matching_cards(self):
        for question, prefix in (
            ("Who won GPI 2025 Player of the Year?", "22"),
            ("Who founded the World Poker Tour?", "23"),
        ):
            with self.subTest(question=question):
                hits = retrieval.search(question, language="EN")
                self.assertTrue(hits)
                self.assertTrue(hits[0].card.slug.startswith(prefix))

    def test_plo_questions_route_to_plo_cards(self):
        for question, prefix in (
            ("PLO มือเริ่มต้นแบบไหนดี", "25"),
            ("ไพ่ KKQJ double suited ดีไหม", "25"),
            ("พีแอลโอ มือ JT98 เล่นยังไง", "25"),
            ("Omaha flop ได้ second set เจอ bet ควร fold ไหม", "26"),
            ("wrap 13 ใบ ควร bet ไหม", "26"),
            ("PLO Hi Lo ควรเล่นมือแบบไหน", "27"),
        ):
            with self.subTest(question=question):
                self.assert_routes_to(question, prefix)

    def test_plo_context_carries_drill_explanations(self):
        context, _, pages = brain.gather("ไพ่ KKQJ double suited ดีไหม")
        self.assertIn("K♠K♦Q♦J♠ (KKQJ double-suited)", context)
        self.assertTrue(pages)

    def test_system_prompt_forbids_claiming_no_plo_knowledge(self):
        self.assertIn("ห้ามอ้างว่าไม่มีความรู้เรื่อง PLO", brain.system_prompt())
