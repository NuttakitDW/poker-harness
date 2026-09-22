# Poker harness

A bilingual, page-cited poker knowledge library from the 26-PDF ZIP archive (25 unique PDFs; one duplicate). Start with [English](harnesses/EN/INDEX.md) or [ไทย](harnesses/TH/INDEX.md). Both editions include topic cards, a glossary, and links to page-organized source extraction; the original PDFs remain in `sources/pdf/`. Thai topic cards are substantive adaptations, not literal translations of every book page. The original PDFs are the canonical full sources. Page-organized extracted text is stored once under `harnesses/EN/sources/`, including the Thai-language PDF; Thai source indexes link back to it.

Consult the [source quality notes](harnesses/EN/sources/source-quality.md) for extraction limits. Some tables, diagrams and suit symbols require checking the original PDF. Older strategy books reflect their own game conditions; check variant, stack depth, rake and payout assumptions before applying a claim.

To rebuild the page-organized source corpus from `Poker book-20260922T043840Z-1-001.zip`, install Python 3.10+ and Poppler (`pdfinfo`, `pdftotext`, `pdfimages`, `pdftoppm`). OCR also needs Tesseract or macOS `swiftc`/Vision. The build updates generated source pages, indexes, and the manifest. The guide builder uses that manifest and curated page mappings to regenerate both language editions. Topic cards are maintained separately.

```sh
python3 scripts/build_source_corpus.py --ocr
python3 scripts/build_guides.py
python3 -m unittest discover -s tests -v
python3 scripts/validate_harness.py
```
