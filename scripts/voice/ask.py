"""ถามคลังความรู้โป๊กเกอร์แล้วให้ตอบเป็นเสียง

ใช้:
    .venv/bin/python scripts/voice/ask.py "ICM ตอน bubble ทำอะไร"
    .venv/bin/python scripts/voice/ask.py --audio tests/fixtures/voice/real/03.wav
    .venv/bin/python scripts/voice/ask.py --live
    .venv/bin/python scripts/voice/ask.py --live --trace
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import barge  # noqa: E402
import brain  # noqa: E402
import chart_grid  # noqa: E402
import costs  # noqa: E402
import journal  # noqa: E402
from engines import usable_text as engines_usable  # noqa: E402
import speech  # noqa: E402
import spoken  # noqa: E402
import streaming  # noqa: E402


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


def respond(question: str, language: str, voice: str, silent: bool,
            history: brain.Conversation | None = None,
            reasoning: bool = True,
            provider: str = speech.DEFAULT_PROVIDER,
            show_chart: bool = True) -> tuple[float, str, tuple[str, ...]]:
    """ตอบหนึ่งคำถาม คืนเวลาถึงเสียงแรก คำตอบที่พูดไป และหน้าต้นฉบับที่ส่งเข้าโมเดล"""
    import speak as player

    began = time.perf_counter()
    if show_chart:
        show_grid(brain.chart_question(question, history), None)
    (cards, pages), pieces = brain.stream_answer(question, language=language,
                                                 history=history, reasoning=reasoning,
                                                 chart_on_screen=show_chart)
    if reasoning:
        pieces = _speech_only(pieces, brain.SAY_MARKER, [])

    say = None if silent else speech.synthesizer(provider, voice)
    queue = None if silent else player.SpeechQueue()
    first_audio = 0.0
    spoken_parts: list[str] = []

    try:
        for sentence in streaming.sentences(pieces):
            spoken_parts.append(sentence)
            print(sentence)
            if silent:
                continue
            audio, _ = say(spoken.to_speech(sentence))
            if not first_audio:
                first_audio = time.perf_counter() - began
            queue.add(audio)
    finally:
        if queue:
            queue.close()

    if not spoken_parts:
        print("ไม่มีคำตอบ", file=sys.stderr)
    if cards:
        print(f"\nอ้างอิงการ์ด: {', '.join(cards)}")
    if pages:
        print(f"หน้าต้นฉบับ: {', '.join(pages)}")
    return first_audio or (time.perf_counter() - began), " ".join(spoken_parts), pages


# ตัวถอดเสียงตัวเดียวที่ฟังไมค์เองได้ ตัวอื่นต้องให้ VAD ในเครื่องตัดประโยคให้ก่อน
STREAMING_ENGINE = "soniox-rt"

ECHO_TAIL_SECONDS = 0.45
AUDIO_START_TIMEOUT = 30.0
# ยอมต่อท่อนที่ถูกตัดเพราะยาวเกินได้ถึงเท่านี้ เกินกว่านี้ตอบเท่าที่ได้ยินก่อน
MAX_MERGED_SECONDS = 120.0
# ลูกชุบเลือกเงียบฟังต่อแล้ว ถ้าผู้ใช้เงียบนานเท่านี้ถือว่าพูดจบ ถึงตาตอบ
LISTEN_PATIENCE_SECONDS = 4.0
# เบากว่านี้เป็นเสียงลมหรือเสียงพิมพ์ ส่งให้ถอดเสียงมีแต่จะได้คำที่ไม่มีใครพูด
MIN_SPEECH_PEAK = 0.02
WARM_UP_SECONDS = 0.5


def show_grid(wanted: str, shown: tuple | None) -> tuple | None:
    """พิมพ์ตาราง 13x13 ของชาร์ตที่ตรงกับคำถาม คืนกุญแจของชาร์ตที่โชว์อยู่

    ถามต่อเรื่องเดิมจะได้ชาร์ตใบเดิม ไม่ต้องพิมพ์ซ้ำให้จอรก
    """
    if not wanted:
        return shown
    found = chart_grid.for_question(wanted, color=sys.stdout.isatty())
    if found is None:
        return shown
    key, grid = found
    if key != shown:
        print(f"\n{grid}\n")
        journal.note("chart", key=list(key))
    return key


def _speech_only(pieces, marker: str, thoughts: list):
    """เก็บส่วนคิดไว้ดูบนจอ คายออกมาเฉพาะส่วนที่จะพูด"""
    for channel, text in streaming.split_reasoning(pieces, marker, brain.THINK_MARKER):
        if channel == "think":
            thoughts.append(text)
            journal.note("reasoning", text=text)
            continue
        yield text


def _mark_first(pieces, marks: list):
    """ส่งชิ้นข้อความผ่านไปเฉย ๆ แต่จดเวลาที่ชิ้นแรกมาถึง ใช้แยกเวลารอโมเดล"""
    for piece in pieces:
        if not marks:
            marks.append(time.perf_counter())
        yield piece


def warm_up(engine: str) -> float:
    """เรียกตัวถอดเสียงหนึ่งครั้งด้วยความเงียบ ให้โหลดโมเดลเสร็จก่อนเริ่มคุย

    ถ้าไม่อุ่นไว้ รอบแรกจะช้าหลายวินาที ผู้ใช้พูดต่อระหว่างนั้นแล้วรอบแรกถูกตัดทิ้ง
    """
    import listen
    import numpy

    silence = numpy.zeros(int(WARM_UP_SECONDS * listen.SAMPLE_RATE), dtype=numpy.float32)
    began = time.perf_counter()
    transcribe_samples(silence, engine)
    return time.perf_counter() - began


def live(args: argparse.Namespace) -> int:
    """สนทนาสดผ่านไมโครโฟน

    ไมค์ถูกฟังในเธรดแยก ลูปนี้จึงรับแต่ช่วงเสียงที่พูดจบแล้ว ไม่มีเสียงกองค้าง
    ถ้าไม่มีตัวตัดเสียงสะท้อนและไม่ได้ใส่หูฟัง จะปิดหูตัวเองขณะกำลังพูด
    ไม่งั้นไมค์จะได้ยินเสียงตอบของระบบแล้วถือว่าเป็นคำถามใหม่ จนคุยกับตัวเองไม่รู้จบ
    """
    import duplex
    import listen
    import meter as wave
    import speak as playback

    say = None if args.no_speak else speech.synthesizer(args.tts, args.voice)
    costs.reset()
    log = journal.start(None if args.no_log_file else (args.log or journal.default_path()),
                        echo=not args.quiet)
    if log.path:
        print(f"บันทึกไว้ที่ {log.path}")

    # ทางเสียงสองทาง: เล่นเสียงตอบผ่านยูนิตเดียวกับที่จับเสียง ยูนิตจึงลบเสียงตัวเองออกได้
    voice = None
    source = None
    if not args.no_aec and not args.no_speak and args.input_device is None:
        opened = duplex.open_voice()
        if opened is None:
            print("เปิดตัวตัดเสียงสะท้อนไม่ได้ ใช้ไมค์ปกติแทน", file=sys.stderr)
        else:
            voice, source = opened

    # คลื่นตอนพูดบอกผู้ใช้ว่าเสียงเข้าแล้ว จะได้ไม่พูดซ้ำเพราะคิดว่าไมค์ไม่ติด
    meter = None if args.no_meter else wave.Meter()
    # ตัวถอดเสียงทางสตรีมฟังไมค์เองและตัดประโยคเอง จึงไม่ต้องผ่าน VAD ในเครื่อง
    if args.engine == STREAMING_ENGINE:
        import soniox_api
        import soniox_rt

        listener = soniox_rt.LiveListener(soniox_api.load_api_key(),
                                          device=args.input_device, source=source,
                                          meter=meter)
    else:
        listener = listen.Listener(device=args.input_device, source=source, meter=meter)
    player: playback.SpeechQueue | None = None
    watch: barge.BargeWatch | None = None
    conversation = brain.Conversation()
    unfinished = ""
    merged = 0.0
    shown_chart: tuple | None = None
    # ผู้ใช้เพิ่งพูดแทรกลูกชุบ ตาถัดไปต้องตอบสั้นแล้วฟังต่อ
    interrupted = False
    # ลูกชุบกำลังเงียบฟังคนที่ยังพูดไม่จบ
    awaiting = False

    # ตัวถอดเสียงในเครื่องต้องโหลดโมเดลก่อน ส่วนทางสตรีมพร้อมใช้ทันทีที่เปิดสาย
    if args.engine != STREAMING_ENGINE:
        print("กำลังอุ่นเครื่องถอดเสียง โหลดโมเดลครั้งเดียว รอสักครู่")
        try:
            journal.note("warm-up", seconds=round(warm_up(args.engine), 2), engine=args.engine)
        except KeyboardInterrupt:
            print("\nยกเลิกก่อนเริ่ม")
            journal.stop()
            return 0
    print("กำลังฟัง พูดได้เลย  หยุดด้วย Ctrl-C")
    if not listener.wait_ready(AUDIO_START_TIMEOUT):
        print("เสียงเข้าไม่เริ่มไหล ตรวจสิทธิ์ไมโครโฟน", file=sys.stderr)
        return 1
    # ตัดเสียงสะท้อนได้ หรือใส่หูฟังอยู่ เสียงตอบก็ไม่วนกลับเข้าไมค์ จึงพูดแทรกได้
    full_duplex = voice is not None or args.headphones
    journal.note("start", full_duplex=full_duplex, echo_cancel=voice is not None,
                 engine=args.engine, language=args.language, tts=args.tts, voice=args.voice,
                 speaking=not args.no_speak, device=args.input_device)
    if voice is not None:
        print("โหมด: พูดแทรกได้ (ตัดเสียงสะท้อนแล้ว)")
    else:
        print("โหมด: พูดแทรกได้" if full_duplex
              else "โหมด: ผลัดกันพูด (เปิดลำโพงได้ ไม่คุยกับตัวเอง)")

    if meter is not None:
        meter.start()
    try:
        while True:
            utterance = listener.take(LISTEN_PATIENCE_SECONDS if awaiting else None)
            if utterance is None:
                # เงียบฟังอยู่แล้วเขาก็เงียบตาม ถือว่าพูดจบ เอาที่ได้ยินมาตอบ
                if not awaiting or listener.speaking or listener.waiting:
                    continue
                awaiting = False
                question, unfinished, merged = unfinished, "", 0.0
                heard_at = 0.0
                journal.note("listen-timeout", text=question)
            else:
                heard_at = utterance.closed_at

                if watch:
                    watch.stop()
                    if watch.fired:
                        interrupted = True
                        journal.note("barge-in", during="playback")
                    watch = None
                if player:
                    if full_duplex and player.busy:
                        player.interrupt()
                        interrupted = True
                        journal.note("barge-in", during="playback")
                    player.close()
                    player = None

                lag = time.monotonic() - utterance.closed_at
                peak = float(abs(utterance.samples).max())
                journal.note("utterance", seconds=round(utterance.seconds, 2), peak=round(peak, 4),
                             cut_short=utterance.cut_short, lag=round(lag, 2),
                             silence_before=round(utterance.silence_before, 2))
                if utterance.text is None and peak < MIN_SPEECH_PEAK:
                    journal.note("ignored", reason="เสียงเบาเกินกว่าจะเป็นคำพูด", peak=round(peak, 4))
                    continue
                if utterance.text is None:
                    heard, stt_seconds = transcribe_samples(utterance.samples, args.engine)
                else:
                    # ถอดเสร็จตั้งแต่ระหว่างพูดแล้ว ไม่มีเวลารอถอดหลังพูดจบ
                    heard, stt_seconds = utterance.text, 0.0
                journal.note("heard", text=heard, stt=round(stt_seconds, 2))
                if not engines_usable(heard, args.language):
                    journal.note("ignored", reason="ถอดเป็นคำที่เชื่อไม่ได้", text=heard)
                    continue
                question = f"{unfinished} {heard}".strip()
                unfinished = ""
                awaiting = False
                merged += utterance.seconds
                print(f"\nคุณ: {question}")
                # ถูกตัดเพราะพูดยาวชนเพดาน ไม่ใช่เพราะพูดจบ จึงรอท่อนต่อไปแล้วตอบทีเดียว
                if utterance.cut_short and merged < MAX_MERGED_SECONDS:
                    unfinished = question
                    journal.note("continuation", reason="ตัดเพราะยาวชนเพดาน",
                                 merged=round(merged, 1))
                    continue
                merged = 0.0
            if not full_duplex:
                listener.mute()
            if not args.no_chart:
                shown_chart = show_grid(brain.chart_question(question, conversation), shown_chart)

            brief = interrupted
            interrupted = False
            may_listen = heard_at > 0.0
            notes = [brain.BRIEF_REMINDER if brief else "",
                     "" if may_listen else brain.SILENCE_REMINDER]
            listening = False
            began = time.perf_counter()
            first = 0.0
            opened = 0.0
            synth_first = 0.0
            said = 0
            spoken_parts: list[str] = []
            thoughts: list[str] = []
            barged = False
            marks: list[float] = []
            cards: tuple[str, ...] = ()
            pages: tuple[str, ...] = ()
            stream = None
            try:
                (cards, pages), pieces = brain.stream_answer(
                    question, language=args.language, history=conversation,
                    reasoning=not args.no_reasoning, chart_on_screen=not args.no_chart,
                    note="\n".join(n for n in notes if n))
                opened = time.perf_counter() - began
                player = None if args.no_speak else playback.SpeechQueue(voice)
                # หยุดเสียงตั้งแต่ผู้ใช้เปิดปากพูด ไม่ต้องรอให้พูดจบประโยค
                if player and full_duplex:
                    watch = barge.BargeWatch(listener, player)
                if not args.no_reasoning:
                    pieces = _speech_only(pieces, brain.SAY_MARKER, thoughts)
                stream = streaming.sentences(_mark_first(pieces, marks))
                for sentence in stream:
                    # ถูกแทรกแล้ว ไม่ต้องเสียเวลาสังเคราะห์ประโยคที่เหลือ
                    if full_duplex and (listener.speaking or listener.waiting
                                        or (watch and watch.fired)):
                        barged = True
                        break
                    if brain.LISTEN_MARKER in sentence:
                        if may_listen and not said:
                            listening = True
                            break
                        sentence = sentence.replace(brain.LISTEN_MARKER, "").strip()
                        if not sentence and said:
                            continue
                        sentence = sentence or brain.LISTEN_NUDGE
                    if brief and said >= barge.BRIEF_MAX_SENTENCES:
                        journal.note("brief-cap", sentences=said)
                        break
                    if brief:
                        sentence = barge.clip(sentence)
                    # คนที่เพิ่งแทรกอาจแค่หยุดคิด รอให้เงียบจริงก่อนค่อยเปิดปาก
                    if brief and not said and barge.hold_for_more(listener, heard_at):
                        barged = True
                        break
                    print(sentence)
                    said += 1
                    spoken_parts.append(sentence)
                    if not player:
                        continue
                    try:
                        chunk, synth = say(spoken.to_speech(sentence))
                    except speech.SpeechError as error:
                        journal.note("sentence-skipped", detail=str(error))
                        continue
                    if not first:
                        first = time.perf_counter() - began
                        synth_first = synth
                    player.add(chunk)
            except brain.BrainError as error:
                journal.note("brain-error", detail=str(error))
            finally:
                if stream is not None:
                    stream.close()

            if barged and player:
                player.interrupt()
                journal.note("barge-in", during="answer", spoken_sentences=said)
            # ถูกแทรกกลางคำตอบ ท่อนถัดไปคือคำแทรกนั้น
            if barged and first:
                interrupted = True
            if listening:
                # เขายังพูดไม่จบ เงียบไว้แล้วเอาท่อนนี้ไปต่อกับท่อนหน้า
                unfinished = question
                awaiting = True
                interrupted = interrupted or brief
                journal.note("listening", text=question)
            elif barged and not first:
                # ยังไม่ได้เริ่มพูดตอบ แปลว่าคนพูดยังไม่จบ ให้เอาท่อนก่อนไปต่อกับท่อนใหม่
                unfinished = question
                # ท่อนนี้ยังเป็นคำแทรกอยู่ ต่อกับท่อนใหม่แล้วก็ยังต้องตอบสั้น
                interrupted = interrupted or brief
                journal.note("continuation", reason="ถูกแทรกก่อนเริ่มตอบ",
                             merged=round(merged, 1))

            # จำไว้ว่าคุยอะไรกันไปแล้ว คำถามถัดไปจะได้ต่อเนื่องโดยไม่ต้องเล่าใหม่
            if not unfinished:
                conversation = conversation.with_turn("user", question)
                answer = " ".join(spoken_parts)
                if answer and barged:
                    answer = f"{answer} (พูดค้างไว้เพราะถูกขัด)"
                conversation = conversation.with_turn("assistant", answer).with_pages(pages)

            journal.note("answer", cards=list(cards[:3]), sentences=said,
                         opened=round(opened, 2),
                         first_token=round((marks[0] - began) if marks else 0.0, 2),
                         first_audio=round(first, 2), synth_first=round(synth_first, 2),
                         total=round(time.perf_counter() - began, 2),
                         barged=barged, brief=brief, text=" ".join(spoken_parts))
            if not full_duplex:
                if player:
                    player.wait_idle()
                time.sleep(ECHO_TAIL_SECONDS)
                listener.unmute()
    except KeyboardInterrupt:
        print("\nจบการสนทนา")
        journal.note("stopped", reason="ผู้ใช้กด Ctrl-C")
    finally:
        if meter is not None:
            meter.stop()
        streamed = getattr(listener, "streamed_seconds", 0.0)
        if streamed:
            costs.record("soniox-stt-rt", costs.soniox_stt_usd(streamed),
                         seconds=round(streamed, 1))
        journal.note("cost", **costs.summary())
        journal.note("end")
        journal.stop()
        if watch:
            watch.stop()
        if player:
            player.interrupt()
            player.close()
        if voice:
            voice.close()
    return 0


def repl(args: argparse.Namespace) -> int:
    """ถามต่อเนื่องหลายคำถาม โหลดโมเดลถอดเสียงครั้งเดียวแล้วใช้ซ้ำ"""
    print("พิมพ์คำถาม หรือพิมพ์พาธไฟล์เสียง  ออกด้วย Ctrl-D หรือพิมพ์ ออก")
    conversation = brain.Conversation()
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
        first, answer, pages = respond(question, args.language, args.voice, args.no_speak,
                                       history=conversation,
                                       reasoning=not args.no_reasoning, provider=args.tts,
                                       show_chart=not args.no_chart)
        conversation = conversation.with_turn("user", question)
        conversation = conversation.with_turn("assistant", answer).with_pages(pages)
        print(f"\nstt {stt_seconds:.2f}s | ถึงเสียงแรก {first:.2f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="ถามคลังความรู้โป๊กเกอร์ด้วยเสียง")
    parser.add_argument("question", nargs="?", help="คำถามแบบข้อความ")
    parser.add_argument("--audio", type=pathlib.Path, help="ไฟล์เสียงคำถาม")
    parser.add_argument("--repl", action="store_true", help="ถามต่อเนื่อง โหลดโมเดลครั้งเดียว")
    parser.add_argument("--live", action="store_true", help="สนทนาสดผ่านไมโครโฟน")
    parser.add_argument("--input-device", type=int, help="หมายเลขอุปกรณ์เสียงเข้า")
    parser.add_argument("--no-aec", action="store_true",
                        help="ไม่ต้องตัดเสียงสะท้อน เล่นเสียงด้วย afplay แบบผลัดกันพูด")
    parser.add_argument("--headphones", action="store_true",
                        help="ใส่หูฟังอยู่ เปิดให้พูดแทรกได้แม้ไม่มีตัวตัดเสียงสะท้อน")
    parser.add_argument("--engine", default=STREAMING_ENGINE, help="ตัวถอดเสียงที่ใช้")
    parser.add_argument("--language", default="TH", choices=["TH", "EN"])
    parser.add_argument("--tts", default=speech.DEFAULT_PROVIDER, choices=speech.PROVIDERS,
                        help="ผู้ให้บริการเสียงพูด")
    parser.add_argument("--voice", help="ชื่อเสียง ค่าเริ่มต้นขึ้นกับผู้ให้บริการ")
    parser.add_argument("--no-speak", action="store_true", help="แสดงข้อความอย่างเดียว")
    parser.add_argument("--log", type=pathlib.Path,
                        help="ที่เก็บบันทึกเหตุการณ์ ค่าเริ่มต้นคือ tmp/logs/live-<เวลา>.jsonl")
    parser.add_argument("--no-log-file", action="store_true",
                        help="โชว์เหตุการณ์บนจอแต่ไม่เขียนไฟล์")
    parser.add_argument("--quiet", action="store_true",
                        help="ไม่ต้องโชว์เหตุการณ์บนจอ")
    parser.add_argument("--no-meter", action="store_true",
                        help="ไม่แสดงคลื่นเสียงระหว่างพูด")
    parser.add_argument("--no-chart", action="store_true",
                        help="ไม่ต้องวาดตารางพรีฟล็อป 13x13 ในเทอร์มินัล")
    parser.add_argument("--no-reasoning", action="store_true",
                        help="ไม่ต้องให้คิดก่อนตอบ ตอบทันทีแบบเดิม")
    args = parser.parse_args()
    if not args.voice:
        args.voice = speech.default_voice(args.tts)

    if args.live:
        return live(args)
    if not args.no_reasoning:
        journal.start(None, echo=not args.quiet)
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

    first, _, _ = respond(question, args.language, args.voice, args.no_speak,
                          reasoning=not args.no_reasoning, provider=args.tts,
                          show_chart=not args.no_chart)
    print(f"\nstt {stt_seconds:.2f}s | ถึงเสียงแรก {first:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
