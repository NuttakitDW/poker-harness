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
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.paxalabs.com/v1/audio/speech"
MODEL = "paxa-tts-flash-v1"
DEFAULT_VOICE = "lukchup"
MAX_CHARS = 5000
RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.6
ROOT = pathlib.Path(__file__).resolve().parents[2]


class SpeechError(RuntimeError):
    """สังเคราะห์เสียงไม่สำเร็จ ผู้เรียกตัดสินเองว่าจะเลิกหรือไปต่อ"""


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
    """คืนข้อมูลเสียงและเวลาที่ใช้เป็นวินาที

    เครือข่ายสะดุดเป็นครั้งคราวเป็นเรื่องปกติ จึงลองซ้ำก่อนยอมแพ้
    และโยนข้อผิดพลาดของตัวเองแทนการสั่งจบโปรแกรม เพื่อให้ลูปสนทนาไปต่อได้
    """
    if len(text) > MAX_CHARS:
        raise SpeechError(f"ข้อความยาว {len(text)} ตัวอักษร เกินขีดจำกัด {MAX_CHARS}")
    payload = json.dumps({"model": MODEL, "input": text, "voice": voice}).encode("utf-8")
    started = time.perf_counter()

    last = ""
    for attempt in range(RETRIES):
        request = urllib.request.Request(
            ENDPOINT,
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read(), time.perf_counter() - started
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:200]
            last = f"Paxa ตอบ {error.code}: {detail}"
            if error.code < 500 and error.code != 429:
                break
        except (urllib.error.URLError, OSError) as error:
            last = f"เรียก Paxa ไม่สำเร็จ: {error}"
        if attempt < RETRIES - 1:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise SpeechError(last or "สังเคราะห์เสียงไม่สำเร็จ")


def play(audio: bytes, register=None) -> None:
    """เล่นเสียงผ่าน afplay โดยไม่ทิ้งไฟล์ค้าง

    register รับตัวกระบวนการไว้ให้ผู้เรียกสั่งหยุดกลางคันได้ ใช้ตอนผู้ใช้พูดแทรก
    """
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        handle.write(audio)
        temp_path = handle.name
    try:
        process = subprocess.Popen(["afplay", temp_path])
        if register:
            register(process)
        process.wait()
    finally:
        if register:
            register(None)
        os.unlink(temp_path)


class SpeechQueue:
    """เล่นเสียงตามลำดับในเธรดเบื้องหลัง เพื่อให้สังเคราะห์ชิ้นถัดไปได้พร้อมกัน"""

    _STOP = object()

    def __init__(self) -> None:
        self._items: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._current: subprocess.Popen | None = None
        self._interrupted = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _register(self, process: subprocess.Popen | None) -> None:
        with self._lock:
            self._current = process

    def _run(self) -> None:
        while True:
            item = self._items.get()
            if item is self._STOP:
                return
            if self._interrupted.is_set():
                continue
            try:
                play(item, register=self._register)
            except (OSError, subprocess.SubprocessError) as error:
                print(f"เล่นเสียงไม่สำเร็จ: {error}", file=sys.stderr)

    def add(self, audio: bytes) -> None:
        """ต่อคิวเสียงหนึ่งชิ้น"""
        if not self._interrupted.is_set():
            self._items.put(audio)

    @property
    def busy(self) -> bool:
        """ยังมีเสียงรออยู่หรือกำลังเล่นอยู่หรือไม่"""
        if not self._items.empty():
            return True
        with self._lock:
            process = self._current
        return bool(process and process.poll() is None)

    @property
    def interrupted(self) -> bool:
        """ถูกสั่งหยุดไปแล้วหรือยัง ใช้เลิกสังเคราะห์ชิ้นที่เหลือ"""
        return self._interrupted.is_set()

    def interrupt(self) -> None:
        """หยุดเสียงที่กำลังเล่นและทิ้งคิวที่เหลือ ใช้เมื่อผู้ใช้พูดแทรก"""
        self._interrupted.set()
        with self._lock:
            process = self._current
        if process and process.poll() is None:
            process.terminate()
        while True:
            try:
                item = self._items.get_nowait()
            except queue.Empty:
                break
            if item is self._STOP:
                self._items.put(self._STOP)
                break

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

    try:
        audio, elapsed = synthesize(text, args.voice, load_api_key())
    except SpeechError as error:
        print(error, file=sys.stderr)
        return 1
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
