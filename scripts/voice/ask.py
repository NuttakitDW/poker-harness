"""ถามคลังความรู้โป๊กเกอร์แล้วให้ตอบเป็นเสียง

ใช้:
    .venv-whisper/bin/python scripts/voice/ask.py "ICM ตอน bubble ทำอะไร"
    .venv-whisper/bin/python scripts/voice/ask.py --audio tests/fixtures/voice/real/03.wav
    .venv-whisper/bin/python scripts/voice/ask.py --live
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import brain  # noqa: E402
import spoken  # noqa: E402
import streaming  # noqa: E402

DEFAULT_VOICE = "lukchup"


def transcribe(audio: pathlib.Path, engine: str) -> tuple[str, float]:
    """ถอดเสียงคำถามจากไฟล์ คืนข้อความและเวลาที่ใช้"""
    import engines

    result = engines.ENGINES[engine](str(audio))
    return result.text, result.seconds


def transcribe_samples(samples, engine: str) -> tuple[str, float]:
    """ถอดเสียงจากตัวอย่างเสียงในหน่วยความจำ ไม่ต้องเขียนไฟล์ลงดิสก์"""
    import engines

    result = engines.ENGINES[engine](samples)
    return result.text, result.seconds


def respond(question: str, language: str, voice: str, silent: bool) -> float:
    """ตอบหนึ่งคำถาม ทยอยพูดทีละประโยค คืนเวลาถึงเสียงแรก"""
    import speak as tts

    began = time.perf_counter()
    (cards, pages), pieces = brain.stream_answer(question, language=language)

    key = None if silent else tts.load_api_key()
    player = None if silent else tts.SpeechQueue()
    first_audio = 0.0
    spoken_parts: list[str] = []

    try:
        for sentence in streaming.sentences(pieces):
            spoken_parts.append(sentence)
            print(sentence)
            if silent:
                continue
            audio, _ = tts.synthesize(spoken.to_speech(sentence), voice, key)
            if not first_audio:
                first_audio = time.perf_counter() - began
            player.add(audio)
    finally:
        if player:
            player.close()

    if not spoken_parts:
        print("ไม่มีคำตอบ", file=sys.stderr)
    if cards:
        print(f"\nอ้างอิงการ์ด: {', '.join(cards)}")
    if pages:
        print(f"หน้าต้นฉบับ: {', '.join(pages)}")
    return first_audio or (time.perf_counter() - began)


ECHO_TAIL_SECONDS = 0.45


def live(args: argparse.Namespace) -> int:
    """สนทนาสดผ่านไมโครโฟน

    ถ้าไม่มีตัวตัดเสียงสะท้อน จะปิดหูตัวเองขณะกำลังพูด ไม่งั้นไมค์จะได้ยิน
    เสียงตอบของระบบแล้วถือว่าเป็นคำถามใหม่ จนคุยกับตัวเองไม่รู้จบ
    """
    import listen
    import speak as tts

    key = None if args.no_speak else tts.load_api_key()
    detector = listen.Detector()
    player: tts.SpeechQueue | None = None
    deaf_until = 0.0
    full_duplex: bool | None = None

    def playing() -> bool:
        return bool(player and player.busy)

    print("กำลังฟัง พูดได้เลย  หยุดด้วย Ctrl-C")
    try:
        for frame in listen.frames(device=args.input_device,
                                   echo_cancel=args.echo_cancel):
            if full_duplex is None:
                full_duplex = listen.echo_cancel_active()
                print("โหมด: พูดแทรกได้" if full_duplex
                      else "โหมด: ผลัดกันพูด (ไม่มีตัวตัดเสียงสะท้อน)")
            if not full_duplex and (playing() or time.monotonic() < deaf_until):
                if playing():
                    deaf_until = time.monotonic() + ECHO_TAIL_SECONDS
                detector.reset()
                continue

            utterance = detector.push(frame)
            if not utterance:
                continue

            if player:
                if full_duplex and player.busy:
                    player.interrupt()
                    print("(หยุดพูดเพราะถูกแทรก)")
                player.close()
                player = None

            heard, stt_seconds = transcribe_samples(utterance.samples, args.engine)
            if not heard.strip():
                continue
            print(f"\nคุณ: {heard}")

            began = time.perf_counter()
            first = 0.0
            cards: tuple[str, ...] = ()
            try:
                (cards, _), pieces = brain.stream_answer(heard, language=args.language)
                player = None if args.no_speak else tts.SpeechQueue()
                for sentence in streaming.sentences(pieces):
                    if player and player.interrupted:
                        break
                    print(sentence)
                    if not player:
                        continue
                    try:
                        audio, _ = tts.synthesize(spoken.to_speech(sentence), args.voice, key)
                    except tts.SpeechError as error:
                        print(f"[พูดไม่ได้ ข้ามประโยคนี้: {error}]", file=sys.stderr)
                        continue
                    if not first:
                        first = time.perf_counter() - began
                    player.add(audio)
            except brain.BrainError as error:
                print(f"[ตอบไม่ได้รอบนี้ ถามใหม่ได้เลย: {error}]", file=sys.stderr)
            print(f"[ฟัง {utterance.seconds:.1f}s | stt {stt_seconds:.2f}s | "
                  f"ถึงเสียงแรก {first:.2f}s | {', '.join(cards[:1])}]")
            deaf_until = time.monotonic() + ECHO_TAIL_SECONDS
    except KeyboardInterrupt:
        print("\nจบการสนทนา")
    finally:
        if player:
            player.interrupt()
            player.close()
    return 0


def repl(args: argparse.Namespace) -> int:
    """ถามต่อเนื่องหลายคำถาม โหลดโมเดลถอดเสียงครั้งเดียวแล้วใช้ซ้ำ"""
    print("พิมพ์คำถาม หรือพิมพ์พาธไฟล์เสียง  ออกด้วย Ctrl-D หรือพิมพ์ ออก")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line or line in ("ออก", "exit", "quit"):
            return 0
        question = line
        stt_seconds = 0.0
        candidate = pathlib.Path(line)
        if candidate.suffix.lower() in (".wav", ".mp3", ".m4a") and candidate.exists():
            question, stt_seconds = transcribe(candidate, args.engine)
            print(f"ได้ยินว่า: {question}\n")
        first = respond(question, args.language, args.voice, args.no_speak)
        print(f"\nstt {stt_seconds:.2f}s | ถึงเสียงแรก {first:.2f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="ถามคลังความรู้โป๊กเกอร์ด้วยเสียง")
    parser.add_argument("question", nargs="?", help="คำถามแบบข้อความ")
    parser.add_argument("--audio", type=pathlib.Path, help="ไฟล์เสียงคำถาม")
    parser.add_argument("--repl", action="store_true", help="ถามต่อเนื่อง โหลดโมเดลครั้งเดียว")
    parser.add_argument("--live", action="store_true", help="สนทนาสดผ่านไมโครโฟน")
    parser.add_argument("--input-device", type=int, help="หมายเลขอุปกรณ์เสียงเข้า")
    parser.add_argument("--echo-cancel", action="store_true",
                        help="ลองใช้ตัวตัดเสียงสะท้อนของระบบ ยังใช้ไม่ได้บน macOS 26")
    parser.add_argument("--engine", default="whisper-biased", help="ตัวถอดเสียงที่ใช้กับไฟล์เสียง")
    parser.add_argument("--language", default="TH", choices=["TH", "EN"])
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--no-speak", action="store_true", help="แสดงข้อความอย่างเดียว")
    args = parser.parse_args()

    if args.live:
        return live(args)
    if args.repl:
        return repl(args)
    if not args.question and not args.audio:
        print("ต้องระบุคำถาม --audio --repl หรือ --live", file=sys.stderr)
        return 1
    if args.audio and not args.audio.exists():
        print(f"ไม่พบไฟล์เสียง: {args.audio}", file=sys.stderr)
        return 1

    stt_seconds = 0.0
    question = args.question
    if args.audio:
        question, stt_seconds = transcribe(args.audio, args.engine)
        print(f"ได้ยินว่า: {question}\n")
    if not question.strip():
        print("ไม่ได้ยินคำถาม", file=sys.stderr)
        return 1

    first = respond(question, args.language, args.voice, args.no_speak)
    print(f"\nstt {stt_seconds:.2f}s | ถึงเสียงแรก {first:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
