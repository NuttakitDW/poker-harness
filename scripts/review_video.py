"""Narrated slide video: each slide is HTML rendered to a 1920x1080 image, voiced in Thai with
Paxa TTS (scripts/voice/speak.py), and joined with ffmpeg into one MP4.

    .venv/bin/python scripts/review_video.py --slides tmp/plo5/video/<tag>/slides.json --out <video.mp4>

slides.json: {"engine": "paxa" | "gemini", "voice": "foithong" | "Charon", "speed": 1.05,
"slides": [{"html": "<section>...</section>", "narration": "ข้อความภาษาไทย"}, ...]}. Paxa reads PAXA_API,
Gemini (gemini-3.8-flash-tts) reads GEMINI_FLASH from .env; Gemini speaks every word it is given, so send
only the script (no style instructions). The slide HTML is placed inside the shared frame below (tamkwai
stage: dotted dark ground, parchment panels, Kanit + IBM Plex). Rendered images and audio are cached
next to slides.json, so editing one slide only redoes that slide.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))

import speak  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
GEMINI_MODEL = "gemini-3.8-flash-tts"


def gemini_speech(text: str, voice: str) -> bytes:
    """WAV bytes from Gemini TTS (retries a few times: the preview endpoint fails now and then)."""
    import keys  # scripts/voice/keys.py reads .env
    key = keys.require("GEMINI_FLASH")
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"
    for attempt in range(10):
        try:
            request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            data = json.load(urllib.request.urlopen(request, timeout=300))
            return base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        except urllib.error.HTTPError as error:  # 429: wait as long as the API asks (RetryInfo), else back off
            if attempt == 9 or error.code not in (429, 500, 503):
                raise
            detail = error.read().decode(errors="replace")
            if "PerDay" in detail:  # daily quota (free tier: 10 requests/day/model): waiting won't help today
                raise RuntimeError("Gemini TTS daily quota used up; enable billing on the GEMINI_FLASH key "
                                   "or rerun tomorrow (finished slides are cached)") from error
            wait = re.search(r'"retryDelay":\s*"(\d+)', detail)
            time.sleep((int(wait.group(1)) + 3) if wait else 20 * (attempt + 1))
        except Exception:  # noqa: BLE001 - network hiccup: retried, then raised
            if attempt == 9:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")
PAD = 0.7  # seconds of silence after each slide's narration

FRAME = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Kanit:wght@500;600;700&family=IBM+Plex+Sans+Thai+Looped:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
  :root { --ground: #171512; --paper: #FBF8EE; --edge: #3A3628; --ink: #14213D; --cream: #F6F2E6; --cream-2: #D8D2BE;
    --muted: #B8AE92; --red: #C6322A; --bronze: #C9A266; --blue: #9FB4DC; --good: #6FBF8B; --warn: #D9A54A; --bad: #EF7468;
    --suit-s: #14213D; --suit-h: #C6322A; --suit-d: #1F5FB8; --suit-c: #2E7D4F; }
  * { box-sizing: border-box; margin: 0; }
  html, body { width: 1920px; height: 1080px; overflow: hidden; background: var(--ground); color: var(--cream);
    font: 400 34px/1.5 "IBM Plex Sans Thai Looped", "Kanit", sans-serif; }
  body::before { content: ""; position: fixed; inset: 0; background-image: radial-gradient(rgba(246,242,230,.10) 1.4px, transparent 1.8px); background-size: 14px 14px; }
  .frame { position: relative; height: 100%; padding: 90px 120px 110px; display: flex; flex-direction: column; gap: 34px; }
  .brand { position: absolute; left: 120px; bottom: 44px; font: 600 26px "Kanit"; color: var(--muted); display: flex; gap: 14px; align-items: center; }
  .brand i { width: 14px; height: 14px; background: var(--red); border-radius: 3px 2px 4px 2px; display: inline-block; }
  .page { position: absolute; right: 120px; bottom: 44px; font: 500 22px "IBM Plex Mono"; color: var(--muted); }
  .eyebrow { font: 500 28px/1.2 "IBM Plex Sans Thai Looped", "IBM Plex Mono"; color: var(--muted); }  /* no letter-spacing: it pulls Thai vowel marks off their letters */
  h1 { font: 700 96px/1.1 "Kanit"; } h2 { font: 600 64px/1.15 "Kanit"; }
  h1 .hoof, h2 .hoof { display: inline-block; width: .3em; height: .3em; background: var(--red); border-radius: 3px 2px 4px 2px; margin-right: .25em; vertical-align: .16em; }
  .lede { color: var(--cream-2); max-width: 1500px; }
  .mono { font-family: "IBM Plex Mono", monospace; }
  .row { display: flex; gap: 28px; flex-wrap: wrap; }
  .panel { background: var(--paper); color: var(--ink); border-radius: 10px 6px 12px 5px; padding: 30px 36px; }
  .stat { display: grid; gap: 6px; min-width: 330px; }
  .stat b { font: 600 84px/1 "IBM Plex Mono"; }
  .stat span { font-size: 28px; color: #4F5667; }
  .A b { color: #2E6B45; } .B b { color: #9A6A1E; } .C b { color: #B3261E; }
  .bar { display: flex; height: 64px; border-radius: 8px; overflow: hidden; width: 100%; }
  .bar i { display: grid; place-items: center; font: 600 28px "IBM Plex Mono"; color: #FBF8EE; }
  .hand { display: grid; grid-template-columns: 1fr auto; gap: 10px 30px; align-items: center; }
  .hand h3 { font: 600 38px "Kanit"; }
  .hand p { font-size: 28px; color: #4F5667; }
  .tag { font: 600 26px "IBM Plex Mono"; padding: 6px 14px; border-radius: 6px; border: 2px solid currentColor; white-space: nowrap; }
  .tag.A { color: #2E6B45; } .tag.B { color: #9A6A1E; } .tag.C { color: #B3261E; }
  .cards { display: inline-flex; gap: 6px; vertical-align: middle; }
  .card { font: 600 30px/1 "IBM Plex Mono"; padding: 8px 9px; background: #fff; border: 2px solid #D9D0B8; border-radius: 7px; }
  .s-s { color: var(--suit-s); } .s-h { color: var(--suit-h); } .s-d { color: var(--suit-d); } .s-c { color: var(--suit-c); }
  ol, ul { padding-left: 1.2em; display: grid; gap: 18px; }
  li::marker { color: var(--red); font-weight: 700; }
  .score { font: 700 260px/1 "IBM Plex Mono"; color: var(--cream); }
  .split { display: grid; grid-template-columns: minmax(0, 1fr) 760px; gap: 48px; align-items: start; }
  .opts { display: grid; gap: 16px; }
  .opt { display: grid; grid-template-columns: 250px 1fr 120px 180px; gap: 18px; align-items: center; font-size: 32px; }
  .opt .barbox { height: 30px; background: #E4DCC6; border-radius: 5px; overflow: hidden; }
  .opt .barbox i { display: block; height: 100%; }
  .opt .p { font: 600 32px "IBM Plex Mono"; text-align: right; }
  .opt .v { font: 500 28px "IBM Plex Mono"; color: #4F5667; text-align: right; }
  .opt.you span:first-child::after { content: " ← เรา"; color: var(--red); font-size: 26px; }
  .chart13 { display: grid; grid-template-columns: repeat(13, 1fr); gap: 3px; }
  .chart13 div { position: relative; height: 40px; background: #2A2722; display: flex; overflow: hidden; border-radius: 3px; }
  .chart13 div i { display: block; height: 100%; }
  .chart13 div b { position: absolute; inset: 0; display: grid; place-items: center; font: 600 15px "IBM Plex Mono"; color: #FBF8EE; text-shadow: 0 0 3px rgba(0,0,0,.8); }
  .chart13 div.faint { opacity: .35; }
  .chart13 div.mine { outline: 3px solid #FBF8EE; outline-offset: -2px; z-index: 1; }
  .legend13 { display: flex; gap: 22px; font-size: 24px; color: var(--cream-2); margin-top: 10px; }
  .legend13 i { display: inline-block; width: 18px; height: 18px; border-radius: 3px; margin-right: 8px; vertical-align: -2px; }
  .board { font-size: 30px; color: var(--cream-2); }
  .score small { font-size: 90px; color: var(--muted); }
</style></head><body><div class="frame">BODY</div>
<div class="brand"><i></i>ตามควาย · BRAND</div><div class="page">PAGE</div></body></html>"""


def render(html: str, page: str, png: Path, brand: str = "รีวิว session") -> None:
    page_html = FRAME.replace("BODY", html).replace("PAGE", page).replace("BRAND", brand)
    src = png.with_suffix(".html")
    src.write_text(page_html)
    command = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
               f"--user-data-dir={png.parent.resolve() / '.chrome'}", "--virtual-time-budget=4000", "--window-size=1920,1080",
               f"--screenshot={png.resolve()}", src.resolve().as_uri()]
    for attempt in range(3):  # headless Chrome now and then exits 2 on start-up; a retry clears it
        run = subprocess.run(command, capture_output=True, text=True)
        if run.returncode == 0 and png.exists():
            return
        time.sleep(2)
    raise RuntimeError(f"Chrome could not render {src}: {run.stderr[-400:]}")


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def build(spec_path: Path, out: Path) -> Path:
    spec = json.loads(spec_path.read_text())
    work = spec_path.parent / "build"
    work.mkdir(parents=True, exist_ok=True)
    engine = spec.get("engine", "paxa")
    key = speak.load_api_key() if engine == "paxa" else None
    voice, speed = spec.get("voice", "foithong" if engine == "paxa" else "Charon"), float(spec.get("speed", 1.05))
    brand = spec.get("brand", "รีวิว session")
    parts = []
    slides = spec["slides"]
    for i, slide in enumerate(slides):
        tag = hashlib.sha1((slide["html"] + slide["narration"] + engine + voice + str(speed) + brand).encode()).hexdigest()[:10]
        audio_tag = hashlib.sha1((slide["narration"] + engine + voice + str(speed)).encode()).hexdigest()[:10]
        png, mp4 = work / f"{i:02d}-{tag}.png", work / f"{i:02d}-{tag}.mp4"
        mp3 = work / f"voice-{audio_tag}.{'mp3' if engine == 'paxa' else 'wav'}"  # survives slide-only edits
        if not png.exists():
            render(slide["html"], f"{i + 1} / {len(slides)}", png, brand)
        if not mp3.exists():
            if engine == "paxa":
                audio, _ = speak.synthesize(slide["narration"], voice, key, speed)
            else:
                audio = gemini_speech(slide["narration"], voice)
            mp3.write_bytes(audio)
        if not mp4.exists():
            length = duration(mp3) + PAD
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", str(mp3),
                            "-filter_complex",
                            f"[0:v]scale=1920:1080,format=yuv420p,fade=t=in:st=0:d=0.35,fade=t=out:st={length - 0.35:.2f}:d=0.35[v];"
                            f"[1:a]apad=pad_dur={PAD},aresample=48000[a]",
                            "-map", "[v]", "-map", "[a]", "-t", f"{length:.2f}", "-r", "30", "-c:v", "libx264",
                            "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", str(mp4)], check=True)
        parts.append(mp4)
        print(f"slide {i + 1}/{len(slides)}: {duration(mp4):.1f}s", flush=True)
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    print(f"{out}: {duration(out):.0f}s", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slides", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.slides, args.out)


if __name__ == "__main__":
    main()
