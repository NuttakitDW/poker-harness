"""Checks for routing a spoken question to the right topic card."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
import corpus  # noqa: E402
import retrieval  # noqa: E402


class CorpusTests(unittest.TestCase):
    def test_both_language_editions_load(self):
        languages = {card.language for card in corpus.load_cards()}
        self.assertEqual(languages, {"TH", "EN"})

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
