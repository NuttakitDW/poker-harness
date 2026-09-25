"""วัดทั้งสาย เสียง -> ตัวถอดเสียง -> ตัวอ่าน regex บนคำถาม spot ที่พูดเป็นไทย

คำพูดกับเฉลยอยู่ที่ tests/fixtures/spot/spoken.jsonl เสียงสร้างด้วย Paxa TTS ครั้งแรกครั้งเดียว
เก็บไว้ที่ tmp/stt/spot-audio (ไฟล์เสียงไม่เข้า git) แล้วถอดด้วย Soniox ตาม context ที่เลือก

ใช้:
    .venv/bin/python scripts/voice/spot_audio_eval.py --context general spot
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import soniox_api
import spot_eval

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPOKEN = ROOT / "tests" / "fixtures" / "spot" / "spoken.jsonl"
AUDIO_DIR = ROOT / "tmp" / "stt" / "spot-audio"
VOICE = "foithong"


def synthesize(case: dict, folder: pathlib.Path = AUDIO_DIR) -> pathlib.Path:
    """ไฟล์ wav 16k mono ของคำพูดหนึ่งข้อ สร้างด้วย Paxa TTS ถ้ายังไม่มี"""
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f"{case['id']}.wav"
    if wav.exists():
        return wav
    mp3 = wav.with_suffix(".mp3")
    subprocess.run([sys.executable, str(ROOT / "scripts/voice/speak.py"), case["spoken"],
                    "--voice", VOICE, "--no-play", "--out", str(mp3)], check=True,
                   capture_output=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
    mp3.unlink()
    return wav


def run(context_name: str, cases: list[dict]) -> spot_eval.Result:
    """ถอดทุกไฟล์ด้วย context ที่เลือก แล้วให้คะแนนการอ่าน"""
    key = soniox_api.load_api_key()
    heard = {}
    for case in cases:
        path = synthesize(case)
        heard[case["id"]] = soniox_api.transcribe_bytes(path.read_bytes(), key, path.name,
                                                        context_name).text
    rows = [{**case, "question": heard[case["id"]], "source": context_name} for case in cases]
    return spot_eval.evaluate(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="วัดเสียง -> ถอดเสียง -> อ่าน spot")
    parser.add_argument("--context", nargs="+", default=["general", "spot"],
                        choices=sorted(soniox_api.CONTEXTS))
    parser.add_argument("--failures", action="store_true")
    args = parser.parse_args()
    cases = [json.loads(line) for line in SPOKEN.read_text(encoding="utf-8").splitlines() if line]
    for name in args.context:
        print(f"\n===== context: {name}")
        print(run(name, cases).render(failures_only=args.failures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
