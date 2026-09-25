"""สังเคราะห์เสียงพูดผ่าน Soniox Text-to-Speech

ทำหน้าที่เดียวกับ speak.synthesize แต่คนละเจ้า เพื่อเทียบเสียงกันได้ในสนามเดียวกัน
และเพื่อให้สลับผู้ให้บริการได้โดยไม่ต้องแก้ลูปสนทนา

ใช้:
    python scripts/voice/soniox_tts.py "ข้อความ" --voice Nurul --out tmp/tts/out.mp3
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Iterator

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import costs  # noqa: E402
import keys  # noqa: E402

ENDPOINT = "https://tts-rt.soniox.com/tts"
WEBSOCKET_URL = "wss://tts-rt.soniox.com/tts-websocket"
# ด่านหน้าของ Soniox ปฏิเสธ User-Agent ปริยายของ urllib ด้วย 403 ต้องบอกชื่อตัวเองไป
USER_AGENT = "tamkwai/1.0"
MODEL = "tts-rt-v2"
# รุ่นสตรีมใช้ v1 เพราะ v2 ใช้เวลาสังเคราะห์นานกว่าหลายเท่าจนคุยสดไม่ได้
STREAM_MODEL = "tts-rt-v1"
LANGUAGE = "th"
DEFAULT_VOICE = "Hazel"
AUDIO_FORMAT = "mp3"
RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.6
TIMEOUT_SECONDS = 90


class SpeechError(RuntimeError):
    """สังเคราะห์เสียงไม่สำเร็จ ผู้เรียกตัดสินเองว่าจะเลิกหรือไปต่อ"""


def load_api_key() -> str:
    """คีย์ Soniox จาก environment หรือ .env"""
    return keys.require("SONIOX_API", "SONIOX_API_KEY")


def _charge(text: str, seconds: float) -> None:
    """คิดเงินหนึ่งประโยค ความยาวเสียงเดาจากข้อความเพราะได้ mp3 กลับมา ไม่ใช่เสียงดิบ"""
    costs.record("soniox-tts", costs.soniox_tts_usd(len(text)), quantity=len(text),
                 seconds=seconds, estimated=True)


def synthesize(text: str, voice: str, key: str, language: str = LANGUAGE) -> tuple[bytes, float]:
    """คืนข้อมูลเสียงและเวลาที่ใช้เป็นวินาที ลองซ้ำเมื่อเครือข่ายสะดุด"""
    payload = json.dumps({
        "model": MODEL,
        "language": language,
        "voice": voice,
        "audio_format": AUDIO_FORMAT,
        "text": text,
    }).encode("utf-8")
    started = time.perf_counter()

    last = ""
    for attempt in range(RETRIES):
        request = urllib.request.Request(
            ENDPOINT,
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                audio = response.read()
            elapsed = time.perf_counter() - started
            _charge(text, elapsed)
            return audio, elapsed
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:200]
            last = f"Soniox ตอบ {error.code}: {detail}"
            if error.code < 500 and error.code != 429:
                break
        except (urllib.error.URLError, OSError) as error:
            last = f"เรียก Soniox ไม่สำเร็จ: {error}"
        if attempt < RETRIES - 1:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise SpeechError(last or "สังเคราะห์เสียงไม่สำเร็จ")


def stream(text: str, voice: str, key: str, language: str = LANGUAGE,
           model: str = STREAM_MODEL) -> Iterator[bytes]:
    """คายเสียงทีละชิ้นระหว่างที่ยังสังเคราะห์ไม่จบ ชิ้นแรกมาถึงในราวครึ่งวินาที

    ทางนี้เปิดสายใหม่ต่อหนึ่งประโยค เพราะลูปสนทนาสังเคราะห์ทีละประโยคอยู่แล้ว
    และสายที่เปิดค้างไว้จะถูกฝั่งบริการปิดเองเมื่อเงียบนานเกินไป
    """
    from websockets.sync.client import connect

    stream_id = uuid.uuid4().hex
    # ปิดการหยั่งสายอัตโนมัติ ฝั่งบริการเงียบระหว่างสังเคราะห์นานกว่าเวลารอปริยาย
    # แล้วไลบรารีจะตัดสายทิ้งทั้งที่เสียงกำลังจะมา
    with connect(WEBSOCKET_URL, user_agent_header=USER_AGENT,
                 open_timeout=TIMEOUT_SECONDS, ping_interval=None) as socket:
        socket.send(json.dumps({
            "api_key": key,
            "stream_id": stream_id,
            "model": model,
            "language": language,
            "voice": voice,
            "audio_format": AUDIO_FORMAT,
        }))
        socket.send(json.dumps({"text": text, "text_end": False, "stream_id": stream_id}))
        socket.send(json.dumps({"text": "", "text_end": True, "stream_id": stream_id}))

        while True:
            message = json.loads(socket.recv(timeout=TIMEOUT_SECONDS))
            if message.get("error_code") is not None:
                raise SpeechError(
                    f"Soniox ตอบ {message['error_code']}: {message.get('error_message', '')}")
            audio = message.get("audio")
            if audio:
                yield base64.b64decode(audio)
            if message.get("terminated"):
                return


def stream_synthesize(text: str, voice: str, key: str,
                      language: str = LANGUAGE) -> tuple[bytes, float]:
    """เหมือน synthesize แต่ไปทางสตรีม ซึ่งเร็วกว่าทาง REST หลายเท่า"""
    started = time.perf_counter()
    try:
        chunks = list(stream(text, voice, key, language))
    except SpeechError:
        raise
    except Exception as error:  # สายขาดกลางคัน ผู้เรียกควรได้ข้อผิดพลาดชนิดเดียวกันเสมอ
        raise SpeechError(f"สตรีมเสียงจาก Soniox ไม่สำเร็จ: {error}") from error
    elapsed = time.perf_counter() - started
    _charge(text, elapsed)
    return b"".join(chunks), elapsed


def voices(key: str, model: str = MODEL) -> tuple[dict, ...]:
    """รายชื่อเสียงสำเร็จรูปพร้อมลักษณะของแต่ละเสียง ใช้ตอนคัดเสียง"""
    found: list[dict] = []
    cursor = ""
    while True:
        request = urllib.request.Request(
            f"https://api.soniox.com/v1/shared-voices?model={model}&cursor={cursor}",
            headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                page = json.load(response)
        except (urllib.error.URLError, OSError) as error:
            raise SpeechError(f"ขอรายชื่อเสียงไม่สำเร็จ: {error}") from error
        found.extend(page.get("voices", []))
        cursor = page.get("next_page_cursor")
        if not cursor:
            return tuple(found)


def main() -> int:
    parser = argparse.ArgumentParser(description="พูดข้อความไทยผ่าน Soniox TTS")
    parser.add_argument("text", nargs="?", help="ข้อความ (ถ้าไม่ใส่จะอ่านจาก stdin)")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--language", default=LANGUAGE)
    parser.add_argument("--out", type=pathlib.Path, help="บันทึกไฟล์เสียงไว้ด้วย")
    parser.add_argument("--no-play", action="store_true", help="ไม่ต้องเล่นออกลำโพง")
    parser.add_argument("--list-voices", action="store_true", help="แสดงรายชื่อเสียงทั้งหมด")
    args = parser.parse_args()

    key = load_api_key()
    if args.list_voices:
        for voice in voices(key):
            print(f"{voice['id']:14} {voice['gender']:7} {voice['age']:12} "
                  f"{voice['accent']:16} {','.join(voice['style'])}")
        return 0

    text = (args.text if args.text is not None else sys.stdin.read()).strip()
    if not text:
        print("ไม่มีข้อความให้พูด", file=sys.stderr)
        return 1

    try:
        audio, elapsed = synthesize(text, args.voice, key, args.language)
    except SpeechError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{args.voice}  {len(text)} ตัวอักษร  {elapsed:.3f}s  {len(audio)} bytes", file=sys.stderr)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(audio)
        print(f"บันทึก: {args.out}", file=sys.stderr)
    if not args.no_play:
        import speak

        speak.play(audio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
