# tamkwai (ตามควาย.com)

Thai-first poker study tools built on our own solvers: preflop and postflop range explorers,
push/fold and ICM charts, research papers, video lessons, and a chart assistant you can ask in
Thai by text, voice or Discord. The site is [tamkwai.com](https://tamkwai.com).

Everything a page shows comes from a solver in this repo. Solves run offline; the site serves
their exported strategies as static files and only computes small things (lookups, river buckets)
in the browser.

## The site

| Page | What it shows |
| --- | --- |
| `/` ถามชาร์ต | Ask for a chart in plain Thai: push/fold, AoF, PLO and ICM open / 3-bet / jam up to `30bb` |
| `/plo` PLO4 range | PLO4 2-6 max at `100/40/20/10bb`, chip EV. Preflop for every stack; at `10bb` the line continues through flop, turn and river |
| `/o8` O8 range | Heads-up fixed-limit Omaha 8-or-better, preflop and flop |
| `/method` วิธีคำนวณ | How the charts are computed |
| `/research` งานวิจัย | Papers (PDF) and explainer pages |
| `/academy` ศาลาเรียน | Video lessons from the YouTube channel, with chapters and links into the explorers |

Pages are plain HTML in `public/`, sharing `public/static/plo-explorer.js` (action line, two-step
hand matrix, filters, hand list) between `/plo`, `/o8` and the local final-table page.

## Solvers

| Package | Game | Used for |
| --- | --- | --- |
| `pushfold/` | NLH push/fold Nash, 2-9 players, chip EV and ICM | `/` charts, AoF |
| `icm_open/` | NLH preflop ICM open / 3-bet / jam | `/` ICM charts |
| `plo_premium_proof/` | PLO4 2-6 max, every street (CFR, 780 preflop buckets, 120 flop / 120 turn / 10 river) | `/plo`, final-table ICM, the premium-fold paper |
| `plo_icm/` | PLO4 game state and small ICM spots | shared by the PLO solvers |
| `plo_equity/` | PLO4 cards, suit classes, Monte Carlo equity | hand classes, equity answers |
| `plo_chipev/`, `plo_chipev_fast/` | Earlier six-max PLO4 preflop research games | research only |
| `o8_fl/` | Heads-up fixed-limit O8 | `/o8` |
| `deepstack-swarm/` | Multi-agent research workspace (own venv) | experiments |

### How the PLO4 explorer data is made

```sh
# 1. Solve: two seeds per table size and stack, all streets (resumable; skips charts already built)
.venv/bin/python scripts/final_table/chart_batch.py

# 2. Preflop: one JSON per game plus the shared hand-class list
.venv/bin/python -m plo_premium_proof.web_export --out public/static --only 6max-10bb

# 3. Postflop (10bb games): flop/turn/river strategy of every line, from the same models
.venv/bin/python -m plo_premium_proof.flop_web strategy --name 6max-10bb \
  --models tmp/plo_premium_proof/6max-10bb-seed-1/model.npz tmp/plo_premium_proof/6max-10bb-seed-2/model.npz

# 4. Bucket tables, shared by every game: 1,755 flops, then 49 turns per flop (resumable)
.venv/bin/python -m plo_premium_proof.flop_web library --out tmp/plo_premium_proof/flops
.venv/bin/python -m plo_premium_proof.flop_web turns --out tmp/plo_premium_proof/turns --workers 8
```

The solver groups hands into buckets, so the page needs each hand's bucket on the chosen board.
Flop and turn buckets (strength, flush draw, straight outs) are precomputed into the tables in
step 4 (about 33 MB for flops, 2.4 GB for turns) and kept outside git; the deploy serves them under
`/static/plo/v1/`. River buckets are hand strength only, so `public/static/plo-river.js`
computes them in the browser; a test checks it against the solver's own bucket code.

The O8 page works the same way through `o8_fl/web_export.py` and `o8_fl/flop_web.py`.

## Running locally

Python 3.12. The website needs only the packages in `pyproject.toml`; the solvers also need
`numba` and `phevaluator`.

```sh
uv sync --extra plo-equity       # creates .venv from uv.lock
uv pip install numba             # solvers only
make web          # the site at http://127.0.0.1:8000 (serves public/ and the local bucket tables)
make ft           # final-table ICM solver page
make admin        # local-only visitor dashboard
make voice        # Thai voice assistant
make bot          # Discord bot
```

Keys go in `.env` (never committed):

| Variable | Needed by |
| --- | --- |
| `DEEPSEEK_API_KEY` (or `DEEPSEEK_API`) | AI answers and image reading in the chat on `/`, the voice assistant and the bots |
| `SONIOX_API`, `PAXA_API` | voice: speech to text and text to speech |
| `DISCORD_BOT_TOKEN` | `make bot` |
| `WEB_STATE_SECRET` | signing per-visitor chat memory on the site |
| `DATABASE_URL` | visitor analytics (SQLite via `ANALYTICS_DB` when unset) |

## Tests

```sh
.venv/bin/python -m unittest discover -s tests
```

Tests live in `tests/`, one folder or file per package. Some compile numba kernels on first run.

## Knowledge library

`harnesses/` is a bilingual, page-cited poker library built from 25 poker books and two
PokerCoaching cheat sheets. Start at [English](harnesses/EN/INDEX.md) or [ไทย](harnesses/TH/INDEX.md).
Both editions have topic cards, a glossary and links to page-organized source text; Thai topic
cards are adaptations, not literal translations. The original PDFs in `sources/pdf/` are the
canonical sources; check [source quality notes](harnesses/EN/sources/source-quality.md) before
trusting a table, diagram or suit symbol from extracted text.

Rebuilding needs Poppler (`pdfinfo`, `pdftotext`, `pdfimages`, `pdftoppm`) and, for OCR,
Tesseract or macOS Vision:

```sh
python3 scripts/build_source_corpus.py --download-external --ocr   # first time; later runs drop --download-external
python3 scripts/build_guides.py
python3 scripts/validate_harness.py
```

## Repository map

```
public/            site pages and static data
api/index.py       site entry point (pages, chart chat, Discord slash commands)
scripts/web/       local server, chat, analytics, method page builder
scripts/voice/     voice assistant and chart answering
scripts/discord_bot/  gateway bot and slash commands
scripts/final_table/  batch solves and the final-table page
research/          paper sources (LaTeX) and the scripts that build their numbers
harnesses/         the knowledge library
tests/             unit tests
tmp/               solver outputs, caches and bucket tables (git-ignored)
```

Copyright © 2026 Nuttakit Kundum. All rights reserved.
