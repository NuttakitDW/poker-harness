"""พูดข้อความไทยผ่าน Paxa TTS Flash แล้วเล่นออกลำโพง

ใช้:
    python scripts/voice/speak.py "ข้อความ"
    echo "ข้อความ" | python scripts/voice/speak.py --voice massaman
    python scripts/voice/speak.py "ข้อความ" --out tmp/tts/out.mp3 --no-play

ต้องมี PAXA_API_KEY ใน .env หรือใน environment
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.paxalabs.com/v1/audio/speech"
MODEL = "paxa-tts-flash-v1"
DEFAULT_VOICE = "lukchup"
MAX_CHARS = 5000
ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_api_key() -> str:
    """อ่านคีย์จาก environment ก่อน แล้วค่อยถอยไปอ่าน .env"""
    key = os.environ.get("PAXA_API_KEY")
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "PAXA_API_KEY":
                return value.strip().strip("'\"")
    raise SystemExit("ไม่พบ PAXA_API_KEY ใน environment หรือ .env")


def synthesize(text: str, voice: str, key: str) -> tuple[bytes, float]:
    """คืนข้อมูลเสียงและเวลาที่ใช้เป็นวินาที"""
    if len(text) > MAX_CHARS:
        raise SystemExit(f"ข้อความยาว {len(text)} ตัวอักษร เกินขีดจำกัด {MAX_CHARS}")
    payload = json.dumps({"model": MODEL, "input": text, "voice": voice}).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            audio = response.read()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Paxa ตอบ {error.code}: {error.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as error:
        raise SystemExit(f"เรียก Paxa ไม่สำเร็จ: {error.reason}")
    return audio, time.perf_counter() - started


def play(audio: bytes) -> None:
    """เล่นเสียงผ่าน afplay โดยไม่ทิ้งไฟล์ค้าง"""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        handle.write(audio)
        temp_path = handle.name
    try:
        subprocess.run(["afplay", temp_path], check=True)
    finally:
        os.unlink(temp_path)


class SpeechQueue:
    """เล่นเสียงตามลำดับในเธรดเบื้องหลัง เพื่อให้สังเคราะห์ชิ้นถัดไปได้พร้อมกัน"""

    _STOP = object()

    def __init__(self) -> None:
        self._items: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            item = self._items.get()
            if item is self._STOP:
                return
            try:
                play(item)
            except (OSError, subprocess.SubprocessError) as error:
                print(f"เล่นเสียงไม่สำเร็จ: {error}", file=sys.stderr)

    def add(self, audio: bytes) -> None:
        """ต่อคิวเสียงหนึ่งชิ้น"""
        self._items.put(audio)

    def close(self) -> None:
        """รอให้เล่นจนหมดคิวแล้วปิดเธรด"""
        self._items.put(self._STOP)
        self._worker.join()


def main() -> int:
    parser = argparse.ArgumentParser(description="พูดข้อความไทยผ่าน Paxa TTS")
    parser.add_argument("text", nargs="?", help="ข้อความ (ถ้าไม่ใส่จะอ่านจาก stdin)")
    parser.add_argument("--voice", default=os.environ.get("PAXA_DEFAULT_VOICE", DEFAULT_VOICE))
    parser.add_argument("--out", type=pathlib.Path, help="บันทึกไฟล์เสียงไว้ด้วย")
    parser.add_argument("--no-play", action="store_true", help="ไม่ต้องเล่นออกลำโพง")
    args = parser.parse_args()

    text = (args.text if args.text is not None else sys.stdin.read()).strip()
    if not text:
        print("ไม่มีข้อความให้พูด", file=sys.stderr)
        return 1

    audio, elapsed = synthesize(text, args.voice, load_api_key())
    print(f"{args.voice}  {len(text)} ตัวอักษร  {elapsed:.3f}s  {len(audio)} bytes", file=sys.stderr)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(audio)
        print(f"บันทึก: {args.out}", file=sys.stderr)
    if not args.no_play:
        play(audio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
