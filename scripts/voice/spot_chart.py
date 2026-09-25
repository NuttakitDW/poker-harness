"""ถาม spot แล้วได้ชาร์ตพรีฟล็อปกลับมาอย่างเดียว ไม่มีคำอธิบาย ไม่มีเสียงพูด

แยกจากลูกชุบทั้งหมด พิมพ์หรือพูดก็ได้ สลับโหมดได้ตลอด ถามไทยหรืออังกฤษก็ได้

ใช้:
    .venv/bin/python scripts/voice/spot_chart.py
    .venv/bin/python scripts/voice/spot_chart.py --voice
    .venv/bin/python scripts/voice/spot_chart.py "BB vs BTN shove 10bb tournament"

คำสั่งระหว่างใช้:
    /v      สลับเป็นโหมดพูด
    /t      สลับเป็นโหมดพิมพ์
    /n      เริ่ม spot ใหม่ ลืมตำแหน่งและสแตกที่คุยกันมา
    /help   วิธีใช้ภาษาไทย  /help en ภาษาอังกฤษ
    /q      ออก

ตอนนี้ตอบได้แค่ชาร์ต push/fold ทัวร์นาเมนต์ที่ solver แก้สด สแตกไม่เกิน 15bb หรือพูดว่า push/fold
อย่างอื่นเช่น open 30bb หรือ cash game ตอบว่ายังไม่มี ไม่เปิดชาร์ตหนังสือแทน

คำถามต่อเนื่องยืมสิ่งที่บอกไว้ตาก่อน เช่น "ขอเปลี่ยนเป็น 8bb" หรือ "เจอ button ไม่ใช่ UTG"
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import queue
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import chart_grid  # noqa: E402
import pushfold_chart  # noqa: E402
import spot  # noqa: E402
from engines import usable_text  # noqa: E402

VOICE_COMMANDS = ("/v", "/voice")
TEXT_COMMANDS = ("/t", "/text")
NEW_COMMANDS = ("/n", "/new")
QUIT_COMMANDS = ("/q", "/quit", "exit", "quit", "ออก")
AUDIO_START_TIMEOUT = 30.0
METER_LABEL = "spot chart กำลังฟัง"

MISSING = {
    "TH": "หา spot ไม่เจอ บอกตำแหน่งด้วย เช่น BB เจอ BTN ออลอิน 10bb",
    "EN": "No spot found. Name a seat, e.g. BB vs BTN shove 10bb",
}
ALL_IN_BY_POSTING = {
    "TH": "ตำแหน่งนี้จ่าย blind กับ ante แล้วหมดตัวพอดี ไม่มีอะไรต้องตัดสินใจ รอดูไพ่ได้เลย",
    "EN": "That seat is all-in from posting the blind and ante; there is no decision to make",
}
PUSH_FOLD_ONLY = {
    "TH": "ตอนนี้ยังไม่มีชาร์ตแบบนี้ หาได้แค่ push/fold ทัวร์นาเมนต์ สแตกไม่เกิน 15bb "
          "หรือบอกว่า push/fold เช่น BTN ออลอิน 10bb",
    "EN": "Not available yet. Only tournament push/fold charts, 15bb or less or say push/fold, "
          "e.g. BTN shove 10bb",
}
HELP = "/v voice  /t text  /n new  /q quit  /h help (/help en English)"
HELP_COMMANDS = ("/help", "/h", "/?")
HELP_TEXT = {
    "th": """spot chart · ตามควาย.com
ถามตำแหน่งกับสแตก ได้ชาร์ต push/fold ที่ solver แก้สด

Usage
  make chart
  .venv/bin/python scripts/voice/spot_chart.py ["คำถาม"] [--voice] [--input-device N]

Commands
  /v, /voice          สลับเป็นโหมดพูด
  /t, /text           สลับเป็นโหมดพิมพ์
  /n, /new            เริ่ม spot ใหม่ ลืมตำแหน่ง สแตก และคนที่ all-in ที่จำไว้
  /h, /help [th|en]   วิธีใช้ ไม่บอกภาษา = ไทย  (/? ก็ได้)
  /q, /quit           ออก  (exit, quit, ออก ก็ได้)

Examples  ตอนนี้มีแค่ push/fold ทัวร์นาเมนต์ chip EV
  shove เป็นคนแรก     BTN ออลอิน 10bb
  เจอคน shove         BB เจอ BTN ออลอิน 8bb
  เจอหลายคน           UTG all-in แล้ว BTN call เราอยู่ SB 5bb
  ขนาดโต๊ะ            heads-up, 6-max, 3 handed  (ไม่บอก = โต๊ะ 8 คน)
  ถามมือ              ถือ K5s  ได้ % ของทุก action
  ถามต่อ              ขอ 12bb, เจอ CO แทน  (ใช้ตำแหน่งจากตาก่อน)

Limits
  สแตกมากกว่า 0 ถึง 15bb ทศนิยมได้ เช่น 5.5bb  หรือพูดว่า push/fold  เกิน 15bb เป็นค่าประมาณ
  สแตกที่บอกคือที่เหลือหลังจ่าย ante  ทุกคนสแตกเท่ากัน
  ทุกคนจ่าย ante 10% ของ BB  เปลี่ยนได้: ante 12.5%, ante 0.2bb, ไม่มี ante
  BB จ่าย ante แทนทั้งโต๊ะ: bb ante หรือ live (ค่าเริ่ม 1bb, bb ante 1.5 ก็ได้)

Colours
  แดง shove  เขียว call  น้ำเงิน fold  ยิ่งอ่อนยิ่งเล่นน้อย (เล่นผสม)""",
    "en": """spot chart · tamkwai
Name a seat and a stack, get a push/fold chart solved on the spot

Usage
  make chart
  .venv/bin/python scripts/voice/spot_chart.py ["question"] [--voice] [--input-device N]

Commands
  /v, /voice          switch to voice
  /t, /text           switch to text
  /n, /new            new spot: forget the remembered seats, stack and shovers
  /h, /help [th|en]   this help; Thai unless en  (/? also works)
  /q, /quit           quit  (exit, quit also work)

Examples  push/fold tournament charts only, chip EV
  first to shove      BTN shove 10bb
  facing a shove      BB vs BTN shove 8bb
  facing several      UTG all-in, BTN call, I'm in the SB 5bb
  table size          heads-up, 6-max, 3 handed  (unstated = 8-handed)
  ask about a hand    hold K5s  gives every action's %
  follow up           12bb, vs CO instead  (keeps the seats from before)

Limits
  stacks above 0 up to 15bb, decimals fine (5.5bb), or say push/fold; above 15bb is approximate
  the stack is what is left after the ante; everyone has the same stack
  everyone antes 10% of the BB; change it: ante 12.5%, ante 0.2bb, no ante
  big blind ante for the table: bb ante or live (1bb by default, or bb ante 1.5)

Colours
  red shove  green call  blue fold  lighter = mixed, played less often""",
}



@dataclasses.dataclass(frozen=True)
class Reply:
    """ผลของคำถามหนึ่ง ยังไม่วาด ให้เทอร์มินัลกับ Discord วาดเองตามแบบของตัวเอง"""

    found: "spot.Spot | None"   # spot ที่เจอ ใช้เป็นความจำตาถัดไป ถ้ามีชาร์ตจะเป็นชาร์ตที่แก้แล้ว
    message: str | None = None  # ข้อความแทนชาร์ต เช่นหาไม่เจอหรือยังไม่มีชาร์ตแบบนี้
    note: str = ""              # บรรทัดสมมติฐานของ solver ใต้ชาร์ต


def reply(prompt: str, memory=None) -> Reply:
    """ชาร์ตของคำถามหนึ่ง หรือข้อความบอกว่าทำไมไม่มีชาร์ต"""
    found = spot.lookup(prompt, memory=memory)
    if found is None:
        return Reply(None, MISSING[spot.language_of(prompt)])
    # ตอบแค่ push/fold ที่แก้สด นอกนั้นบอกว่ายังไม่มี แต่ยังจำตำแหน่งกับสแตกไว้ถามต่อได้
    if pushfold_chart.applies(found.request) and pushfold_chart.all_in_by_posting(found.request):
        return Reply(found, ALL_IN_BY_POSTING[found.lang])
    made = pushfold_chart.solved(found.request) if pushfold_chart.applies(found.request) else None
    if made is None:
        return Reply(found, PUSH_FOLD_ONLY[found.lang])
    return Reply(dataclasses.replace(found, book=made.book, chart=made.chart), note=made.note)


def answer(prompt: str, color: bool, memory=None) -> tuple[str, "spot.Spot | None"]:
    """ข้อความที่จะพิมพ์ในเทอร์มินัลให้หนึ่งคำถาม กับ spot ที่เจอไว้ใช้เป็นความจำตาถัดไป"""
    made = reply(prompt, memory=memory)
    if made.message is not None:
        return made.message, made.found
    found = made.found
    return chart_grid.render(found.book, found.chart, color=color, asked=found.hands,
                             lang=found.lang, notes=(made.note,), show_mixed=False), found


class Session:
    """รับคำถามจากคีย์บอร์ดและไมค์เข้าคิวเดียวกัน ไมค์ส่งเสียงเข้าสายเฉพาะตอนอยู่โหมดพูด"""

    def __init__(self, device: int | None) -> None:
        self.events: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.voice = threading.Event()
        self._device = device
        self._listener = None
        self._meter = None
        threading.Thread(target=self._read_keys, daemon=True).start()

    def _read_keys(self) -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                line = ""
            if not line:
                self.events.put(("eof", ""))
                return
            self.events.put(("typed", line.strip()))

    def _pump_voice(self) -> None:
        while True:
            utterance = self._listener.take()
            if utterance is None or not self.voice.is_set():
                continue
            text = (utterance.text or "").strip()
            if text and usable_text(text, spot.language_of(text)):
                self.events.put(("heard", text))

    def start_voice(self) -> bool:
        """เปิดไมค์ครั้งแรกที่สลับเข้าโหมดพูด ครั้งต่อไปแค่เลิกปิดหู"""
        if self._listener is None:
            import meter
            import soniox_api
            import soniox_rt

            # คลื่นเสียงแบบเดียวกับลูกชุบ ให้เห็นว่าไมค์ได้ยินอยู่ ตอนโหมดพิมพ์ไมค์ปิดหู คลื่นจึงหายเอง
            self._meter = meter.Meter(label=METER_LABEL)
            self._listener = soniox_rt.LiveListener(soniox_api.load_api_key(),
                                                    device=self._device, meter=self._meter)
            if not self._listener.wait_ready(AUDIO_START_TIMEOUT):
                print("เสียงเข้าไม่เริ่มไหล ตรวจสิทธิ์ไมโครโฟน", file=sys.stderr)
                self._listener = None
                self._meter = None
                return False
            self._meter.start()
            threading.Thread(target=self._pump_voice, daemon=True).start()
        else:
            self._listener.unmute()
        self.voice.set()
        return True

    def close(self) -> None:
        """คืน stdout เดิมและลบบรรทัดคลื่นที่ค้าง"""
        if self._meter is not None:
            self._meter.stop()

    def stop_voice(self) -> None:
        """ปิดหู ไม่ส่งเสียงเข้าสาย จะได้ไม่เสียเงินค่าถอดเสียงตอนพิมพ์"""
        self.voice.clear()
        if self._listener is not None:
            self._listener.mute()


def help_for(text: str) -> str | None:
    """วิธีใช้ถ้าข้อความเป็นคำสั่ง /help ไม่บอกภาษาได้ภาษาไทย "/help en" ได้ภาษาอังกฤษ"""
    words = text.strip().lower().split()
    if not words or words[0] not in HELP_COMMANDS or len(words) > 2:
        return None
    lang = words[1] if len(words) == 2 else "th"
    return HELP_TEXT.get(lang)


def _prompt(voice: bool) -> None:
    # โหมดพูดขึ้นบรรทัดใหม่ไว้ให้คลื่นเสียงวาด ไม่งั้นคลื่นจะวาดทับข้อความนี้
    if voice:
        print("\n[voice] พูดได้เลย", flush=True)
    else:
        print("\n[text] > ", end="", flush=True)


def run(args: argparse.Namespace) -> int:
    session = Session(args.input_device)
    try:
        return _loop(args, session)
    finally:
        session.close()


def _loop(args: argparse.Namespace, session: Session) -> int:
    color = sys.stdout.isatty()
    print(f"spot chart  {HELP}")
    if args.voice and not session.start_voice():
        return 1
    _prompt(session.voice.is_set())
    memory = None
    while True:
        try:
            kind, text = session.events.get()
        except KeyboardInterrupt:
            print()
            return 0
        if kind == "eof" or text.lower() in QUIT_COMMANDS:
            print()
            return 0
        if kind == "typed" and text.lower() in VOICE_COMMANDS:
            session.start_voice()
        elif kind == "typed" and text.lower() in TEXT_COMMANDS:
            session.stop_voice()
        elif kind == "typed" and text.lower() in NEW_COMMANDS:
            memory = None
        elif kind == "typed" and help_for(text):
            print(f"\n{help_for(text)}")
        elif text:
            if kind == "heard":
                print(f"\n> {text}")
            shown, found = answer(text, color, memory=memory)
            # หาไม่เจอก็จำของเดิมไว้ พูดเรื่องอื่นแทรกแล้วกลับมาถามต่อได้
            memory = found.request if found else memory
            print(f"\n{shown}")
        _prompt(session.voice.is_set())


def main() -> int:
    parser = argparse.ArgumentParser(description="ถาม spot ได้ชาร์ตพรีฟล็อปอย่างเดียว")
    parser.add_argument("prompt", nargs="?", help="ถามครั้งเดียวแล้วจบ")
    parser.add_argument("--voice", action="store_true", help="เริ่มในโหมดพูด")
    parser.add_argument("--input-device", type=int, help="หมายเลขอุปกรณ์เสียงเข้า")
    args = parser.parse_args()
    if args.prompt:
        print(answer(args.prompt, sys.stdout.isatty())[0])
        return 0
    try:
        return run(args)
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
