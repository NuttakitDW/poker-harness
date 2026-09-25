"""ถาม spot แล้วได้ชาร์ตพรีฟล็อปกลับมาอย่างเดียว ไม่มีคำอธิบาย ไม่มีเสียงพูด

แยกจากลูกชุบทั้งหมด พิมพ์หรือพูดก็ได้ สลับโหมดได้ตลอด ถามไทยหรืออังกฤษก็ได้

ใช้:
    .venv/bin/python scripts/voice/spot_chart.py
    .venv/bin/python scripts/voice/spot_chart.py --voice
    .venv/bin/python scripts/voice/spot_chart.py "BB vs BTN open 40bb tournament"

คำสั่งระหว่างใช้:
    /v      สลับเป็นโหมดพูด
    /t      สลับเป็นโหมดพิมพ์
    /n      เริ่ม spot ใหม่ ลืมตำแหน่งและสแตกที่คุยกันมา
    /q      ออก

คำถามต่อเนื่องยืมสิ่งที่บอกไว้ตาก่อน เช่น "ขอเปลี่ยนเป็น 25bb" หรือ "เจอ button ไม่ใช่ UTG"
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
    "TH": "หา spot ไม่เจอ บอกตำแหน่งด้วย เช่น BB เจอ BTN เปิด 40bb",
    "EN": "No spot found. Name a seat, e.g. BB vs BTN open 40bb",
}
HELP = "/v voice  /t text  /n new spot  /q quit"


def answer(prompt: str, color: bool, classify=spot.systemone_hero,
           memory=None) -> tuple[str, "spot.Spot | None"]:
    """ข้อความที่จะพิมพ์ให้หนึ่งคำถาม กับ spot ที่เจอไว้ใช้เป็นความจำตาถัดไป"""
    found = spot.lookup(prompt, classify=classify, memory=memory)
    if found is None:
        return MISSING[spot.language_of(prompt)], None
    notes = (spot.confidence_line(found),)
    # สแตกสั้นในทัวร์ แก้ push/fold สด ๆ แทนชาร์ตหนังสือที่สแตกไม่ตรง
    made = pushfold_chart.solved(found.request) if pushfold_chart.applies(found.request) else None
    if made is not None:
        found = dataclasses.replace(found, book=made.book, chart=made.chart)
        notes = (made.note,)
    return chart_grid.render(found.book, found.chart, color=color, asked=found.hands,
                             lang=found.lang, notes=notes, show_mixed=False), found


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
