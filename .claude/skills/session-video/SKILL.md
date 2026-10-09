---
name: session-video
description: Make Thai narrated poker videos (MP4) from a reviewed session - a short session summary (A/B/C game grades, score, plan for the C game) or a ~30 minute hand-review episode for ตามควาย followers with solver % bars, $ equity and a range chart per decision, plus the matching /hand-review page data. Voices: Gemini Flash TTS (GEMINI_FLASH) or PaxaLab. Use when the user asks for a video, clip, hand review or spoken summary of a session (e.g. "ทำวิดีโอสรุป session", "รีวิวมือ", "รีวิว A B C game", "ใช้เสียง GEMINI_FLASH", "ใช้เสียง paxalab").
---

# Session review and hand-review videos (Thai)

Turns a session that already has review solves (skill `plo5-icm`: `review_ev.json` per job) into a
~4-5 minute 1080p video: slides in the tamkwai look, Thai narration from Paxa TTS, joined by ffmpeg.
First made for the 2026-10-07 PLO-5 Classic $10 session (`example-slides.json` next to this file).

## 1. Get the numbers

```sh
.venv/bin/python scripts/session_grades.py --hh <session.txt> --review <review dir> \
    --entries 57 --finish 11 --payouts 113.80,93.78,... --out tmp/plo5/video/<tag>/grades.json
```

It grades every **trusted** decision with the review page's rules:

| Grade | Rule |
|---|---|
| A | solver-approved and an action the solver takes 25%+ of the time |
| B | the solver takes it 10-25%, a small leak ($0.05-0.20), or "unclear" (followed the solver but the exact cards disagree) |
| C | costly: the solver takes it under 10% and it cost over $0.20 of tournament equity |

**Decision-quality score** = average of A 100, B 60, C 0. The output also lists A-game highlights
(biggest pots played right), every C decision with the solver's mix, small leaks, and the grade split
by street and position. Read the C list for **patterns** (e.g. ICM jams with weak top pair, passive
turns with big draws, unsteady preflop opens): the improvement plan comes from those, not from one hand.

## 2. Write `tmp/plo5/video/<tag>/slides.json`

`{"voice": "foithong", "speed": 1.05, "slides": [{"html": "...", "narration": "..."}]}`. Follow
`example-slides.json`; the ten-slide structure that worked:

1. Opening: tournament, date, finish / entries, distance to the money, decisions rated
2. How it is scored: ICM solve per hand, what A / B / C mean
3. Overview: A / B / C counts and shares (stat panels + a stacked bar)
4. A game: 3 highlights (board, hand, what we did, solver %)
5. B game: the recurring soft spots, plus the "unclear" count (not mistakes)
6. C game: the single costliest decision, explained (why the solver does otherwise)
7. C game: the other patterns, 2-3 hands
8. Score: big number /100, equity lost, matched-solver %, how the score is computed
9. Plan for the C game: 3 concrete habits tied to the C patterns
10. Summary and sign-off

Slide HTML uses the frame in `scripts/review_video.py`: `.eyebrow`, `h1`/`h2` with `<span class="hoof">`,
`.lede`, `.row`, `.panel`, `.stat` (+ `A`/`B`/`C` colour), `.bar > i`, `.hand` (title, sub-line, `.tag A|B|C`),
`ol`/`ul`, `.score`, `.mono`. Cards: `<span class="cards"><span class="card s-h">A♥</span>…</span>`
(four-colour suits: s, h, d, c). Keep each slide to what fits 1920×1080 without scrolling.

**Narration rules** (Thai, read by TTS):
- **Poker terms stay in English, never translated**: fold (never พับ), call, check, bet, raise, limp,
  all-in, preflop/flop/turn/river, big blind, small blind, button, cutoff, hijack, draw, top pair,
  two pair, set, flush, straight, full house, nuts, solver, ICM, A/B/C game, bubble.
- Numbers and money as Thai words ("สองดอลลาร์กว่า", "เก้าสิบสี่เปอร์เซ็นต์"); no `$`, `%` or `bb` symbols.
  Ranks as words (ควีนคู่, คิกเกอร์คิง); suits as โพดำ / โพแดง / ข้าวหลามตัด / ดอกจิก.
- ครับ / ผม only with a male voice (Gemini `Charon`); with Paxa voices leave them out.
- Every number spoken must come from the solve data (`hand_review.py` prints them) or the HH, never memory.
- About 25-35 seconds of speech per slide; 4-5 minutes in total.
- Keep the tone a coach's: what went well first, then the leaks, then the plan.

## 3. Build, check, deliver (both formats)

```sh
.venv/bin/python scripts/review_video.py --slides tmp/plo5/video/<tag>/slides.json \
    --out tmp/plo5/video/<tag>/session-review-<tag>.mp4
```

- `"engine": "gemini"` (key `GEMINI_FLASH`, model `gemini-3.8-flash-tts`, WAV, voice `Charon`) or
  `"engine": "paxa"` (key `PAXA_API`, voices `foithong`, `massaman`). Gemini reads any instruction text
  aloud: send only the narration. It rate-limits (429) after a few calls; `gemini_speech` waits out the
  API's `retryDelay` and the build resumes from cached audio if it stops. Pace ~13.5 Thai chars/s (Charon); ~20k chars is ~27 min.
- `"brand"` sets the footer label (`รีวิว session` default, `รีวิวมือ` for hand reviews).
- Needs Google Chrome (headless render) and ffmpeg.
- Images and audio are cached in `build/` by content hash: editing one slide redoes only that slide.
  After changing the shared frame CSS, delete `build/*.png build/*.mp4` but keep the `.mp3` files
  (re-voicing costs credits and rate limit).
- Look at the dense slides once (a contact sheet of 3-4 PNGs) before delivering. Never letter-space
  Thai text (it pulls vowel marks off their letters); the frame's eyebrow already avoids it.
- Copy the MP4 to `~/Desktop/` and `open` it; tell the user the length and what each slide covers.

## Hand-review episode (~30 min, for ตามควาย followers)

One `content.json` per episode builds both the video slides and the site data
(`public/static/hand-review/<tag>.json`, listed in `public/static/hand-review/index.json`, shown at `/hand-review`).
Schema in the docstring of `scripts/hand_review.py`; first episode: `tmp/plo5/handreview/2026-10-07/content.json`.

1. Pick ~10 hands with a story from `session_grades.py` output and the review (`collect()`): the bust hand,
   2-3 C-game spots, 2-3 strong A-game decisions (hard folds, value calls), one recurring preflop leak.
   Skip decisions whose $ values look off for the stack (e.g. a 70bb stack worth $3 when neighbours are
   worth $15) - grouped fold-only solves can mismatch seats.
2. Per hand: setup bullets + narration, the decision indexes (order of the hand's rated decisions),
   a short narration per decision, one lesson. Explain *why* the solver acts as it does, and say when
   the % and the $ disagree ("ยังไม่ชัด", hand grouping) instead of calling it a mistake.
3. Real bet sizes come from the HH line (`h["line"]`); the slides show the solver's pot-sized tree, so
   say so when the real bet was smaller.
4. Build: `.venv/bin/python scripts/hand_review.py --content <content.json> --hh <session.txt> --review <dir>
   --entries N --finish N --payouts ... --slides <slides.json> --site public/static/hand-review/<tag>.json`
   (prints slide count and estimated minutes; ~22k narration chars is ~30 min with Gemini), then `review_video.py`.
5. Add the episode to `index.json` (newest first). Preview locally with `scripts/web/server.py`; deploy only
   when the user says so.
