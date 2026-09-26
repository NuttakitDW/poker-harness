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
    /ai-on  คุยภาษาคนแล้วให้ AI เขียนคำถามชาร์ตให้ (ค่าเริ่ม)
    /ai-off โหมดพื้นฐาน อ่านคำถามเองไม่ผ่าน AI
    /help   วิธีใช้ภาษาไทย  /help en ภาษาอังกฤษ
    /contact  อีเมลติดต่อผู้พัฒนา
    /q      ออก

ตอนนี้ตอบได้แค่ชาร์ต push/fold ทัวร์นาเมนต์ที่ solver แก้สด สแตกไม่เกิน 15bb หรือพูดว่า push/fold
และเกม cash All-in or Fold ของ GGPoker (พูด aof)
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

import assistant  # noqa: E402
import chart_grid  # noqa: E402
import mario  # noqa: E402
import pushfold_chart  # noqa: E402
import spot  # noqa: E402
from engines import usable_text  # noqa: E402

VOICE_COMMANDS = ("/v", "/voice")
TEXT_COMMANDS = ("/t", "/text")
NEW_COMMANDS = ("/n", "/new")
QUIT_COMMANDS = ("/q", "/quit", "exit", "quit", "ออก")
CONTACT_COMMANDS = ("/contact",)
CONTACT = "nuttakitkundum@gmail.com"
COPYRIGHT = "© 2026 Nuttakit Kundum. All rights reserved."
AUDIO_START_TIMEOUT = 30.0
METER_LABEL = "spot chart กำลังฟัง"

MISSING = {
    "TH": "หา spot ไม่เจอ บอกตำแหน่งด้วย เช่น BB เจอ BTN ออลอิน 10bb",
    "EN": "No spot found. Name a seat, e.g. BB vs BTN shove 10bb",
}
SEAT_NOT_AT_TABLE = {
    "TH": "ไม่มีชาร์ต: โต๊ะนี้มี {players} คน{why} จึงไม่มีตำแหน่ง {seat} มีแค่ {seats}",
    "EN": "No chart: this table is {players}-handed{why}, so there is no {seat}; the seats are {seats}",
}
# ทำไมโต๊ะมีคนเท่านี้ ตาม SeatProblem.source
SEAT_WHY = {
    "TH": {"said": " ตามที่บอกมา", "aof": " (GG AoF เล่นโต๊ะละ 4 คน)",
           "bubble": " (bubble ของ {entrants} คนลง จ่าย {paid} อันดับ เลยเหลือ {left} คน)",
           "left": " (ทัวร์เหลือ {left} คน)", "default": ""},
    "EN": {"said": " as you said", "aof": " (GG AoF tables seat 4)",
           "bubble": " (bubble of {entrants} entries paying {paid}, so {left} left)",
           "left": " ({left} left in the tournament)", "default": ""},
}
# วิธีแก้ ใช้ตำแหน่งที่มี หรือบอกขนาดโต๊ะที่มีตำแหน่งนั้น ทัวร์สั้นให้บอกคนที่เหลือ นอกนั้นบอกขนาดโต๊ะ
SEAT_FIX = {
    "TH": "แก้ได้: ใช้ตำแหน่งที่มี เช่น {first} ที่พูดก่อนในโต๊ะ {players} คน",
    "EN": "Fix: use a seat that exists, e.g. {first} acts first {players}-handed",
}
SEAT_FIX_SIZE = {
    "TH": {"stage": " หรือถ้ามีคนมากกว่านี้ให้บอกว่า เหลือ {fits} คน",
           "table": " หรือถ้าโต๊ะมีคนมากกว่านี้ให้บอกว่า {fits} handed"},
    "EN": {"stage": ", or if more players are left say {fits} left",
           "table": ", or if more players are seated say {fits} handed"},
}
BAD_PAYOUTS = {
    "TH": "คิด ICM ไม่ได้: {why} ลองบอกขนาดโต๊ะ รางวัล หรือจำนวนคนที่เหลือใหม่ เช่น 4 handed icm 50/30/20",
    "EN": "Can't price ICM: {why}. Try another table size, payouts or players left, "
          "e.g. 4 handed icm 50/30/20",
}
ALL_IN_BY_POSTING = {
    "TH": "ตำแหน่งนี้จ่าย blind กับ ante แล้วหมดตัวพอดี ไม่มีอะไรต้องตัดสินใจ รอดูไพ่ได้เลย",
    "EN": "That seat is all-in from posting the blind and ante; there is no decision to make",
}
PUSH_FOLD_ONLY = {
    "TH": "ตอนนี้ยังไม่มีชาร์ตแบบนี้ หาได้แค่ push/fold ทัวร์นาเมนต์ สแตกไม่เกิน 15bb "
          "หรือบอกว่า push/fold หรือ GG AoF เช่น BTN ออลอิน 10bb หรือ aof BTN",
    "EN": "Not available yet. Only tournament push/fold charts, 15bb or less or say push/fold, "
          "or GG AoF, e.g. BTN shove 10bb or aof BTN",
}
HELP = "/v voice  /t text  /n new  /ai-on /ai-off  /q quit  /h help (/help en English)  /contact"
HELP_COMMANDS = ("/help", "/h", "/?")
# ตัวอย่าง ข้อจำกัด และสี ใช้ร่วมกับวิธีใช้ใน Discord (scripts/discord_bot/bot.py) จะได้ไม่เขียนสองที่
HELP_GUIDE = {
    "th": """Examples  ตอนนี้มีแค่ push/fold ทัวร์นาเมนต์ chip EV หรือ ICM
  shove เป็นคนแรก     BTN ออลอิน 10bb
  เจอคน shove         BB เจอ BTN ออลอิน 8bb
  เจอหลายคน           UTG all-in แล้ว BTN call เราอยู่ SB 5bb
  ขนาดโต๊ะ            heads-up, 6-max, 3 handed  (ไม่บอก = โต๊ะ 8 คน)
  ICM                 icm 50/30/20, รางวัล 50/30/20  (icm เฉย ๆ = bubble เกม live, chip ev = กลับ)
  ช่วงของทัวร์ MTT     เหลือ 50%, เหลือ 120 คน, bubble, final table  เปลี่ยนได้: field 500, paid 12%, avg 25bb
  ถามมือ              ถือ K5s  ได้ % ของทุก action
  ถามต่อ              ขอ 12bb, เจอ CO แทน  (ใช้ตำแหน่งจากตาก่อน)
  GG All-in or Fold   aof BB เจอ CO

Limits
  สแตกมากกว่า 0 ถึง 15bb ทศนิยมได้ เช่น 5.5bb  หรือพูดว่า push/fold  เกิน 15bb เป็นค่าประมาณ
  สแตกที่บอกคือที่เหลือหลังจ่าย ante  ทุกคนสแตกเท่ากัน
  บอกรางวัลเอง ICM นับว่าผู้เล่นที่เหลือทั้งหมดอยู่โต๊ะนี้
  ช่วงของทัวร์: live คนลง 20 ซื้อเข้า 500 บาท เปลี่ยนได้: field 30, buy-in 1000, pool 15000
  bubble = เหลือมากกว่าคนได้เงิน 3%  final table = ทุกคนที่เหลืออยู่โต๊ะนี้
  ทุกคนจ่าย ante 10% ของ BB  เปลี่ยนได้: ante 12.5%, ante 0.2bb, ไม่มี ante
  BB จ่าย ante แทนทั้งโต๊ะ: bb ante หรือ live (ค่าเริ่ม 1bb, bb ante 1.5 ก็ได้)

Colours
  แดง shove  เขียว call  น้ำเงิน fold  ยิ่งอ่อนยิ่งเล่นน้อย (เล่นผสม)""",
    "en": """Examples  push/fold tournament charts only, chip EV or ICM
  first to shove      BTN shove 10bb
  facing a shove      BB vs BTN shove 8bb
  facing several      UTG all-in, BTN call, I'm in the SB 5bb
  table size          heads-up, 6-max, 3 handed  (unstated = 8-handed)
  ICM                 icm 50/30/20, payout 50 30 20  (icm alone = live bubble, chip ev = back)
  MTT stage           50% left, 120 left, bubble, final table  change: field 500, paid 12%, avg 25bb
  ask about a hand    hold K5s  gives every action's %
  follow up           12bb, vs CO instead  (keeps the seats from before)
  GG AoF              aof BB vs CO

Limits
  stacks up to 15bb, decimals ok (5.5bb), or say push/fold; above 15bb is approximate
  the stack is what is left after the ante; everyone has the same stack
  ICM with your payouts: this table is everyone left, unless a stage is given
  stage: 20 entries, 500 THB buy-in; change: field 30, buy-in 1000, pool 15000
  other tables share one stack (this table's unless avg)
  bubble = 3% more players left than places paid; final table = everyone left is at this table
  everyone antes 10% of the BB; change it: ante 12.5%, ante 0.2bb, no ante
  big blind ante for the table: bb ante or live (1bb by default, or bb ante 1.5)

Colours
  red shove  green call  blue fold  lighter = mixed, played less often""",
}
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
  /ai-on              คุยภาษาคน AI เขียนคำถามชาร์ตให้ (ค่าเริ่ม)
  /ai-off             โหมดพื้นฐาน ไม่ผ่าน AI
  /h, /help [th|en]   วิธีใช้ ไม่บอกภาษา = ไทย  (/? ก็ได้)
  /contact            อีเมลติดต่อผู้พัฒนา
  /q, /quit           ออก  (exit, quit, ออก ก็ได้)

""" + HELP_GUIDE["th"] + f"\n\n{COPYRIGHT}",
    "en": """spot chart · tamkwai
Name a seat and a stack, get a push/fold chart solved on the spot

Usage
  make chart
  .venv/bin/python scripts/voice/spot_chart.py ["question"] [--voice] [--input-device N]

Commands
  /v, /voice          switch to voice
  /t, /text           switch to text
  /n, /new            new spot: forget the remembered seats, stack and shovers
  /ai-on              talk naturally, the AI writes the chart query (default)
  /ai-off             basic mode, no AI
  /h, /help [th|en]   this help; Thai unless en  (/? also works)
  /contact            the developer's email
  /q, /quit           quit  (exit, quit also work)

""" + HELP_GUIDE["en"] + f"\n\n{COPYRIGHT}",
}



@dataclasses.dataclass(frozen=True)
class Reply:
    """ผลของคำถามหนึ่ง ยังไม่วาด ให้เทอร์มินัลกับ Discord วาดเองตามแบบของตัวเอง"""

    found: "spot.Spot | None"   # spot ที่เจอ ใช้เป็นความจำตาถัดไป ถ้ามีชาร์ตจะเป็นชาร์ตที่แก้แล้ว
    message: str | None = None  # ข้อความแทนชาร์ต เช่นหาไม่เจอหรือยังไม่มีชาร์ตแบบนี้
    note: str = ""              # บรรทัดสมมติฐานของ solver ใต้ชาร์ต
    # ชนิดคำตอบ ใช้ในบันทึกคำถามเพื่อหาประโยคที่ตัวอ่านยังอ่านไม่ออก
    # chart | not_found | push_fold_only | all_in_by_posting | seat_not_at_table | bad_payouts | mario
    kind: str = "chart"


def reply(prompt: str, memory=None, lang: str | None = None) -> Reply:
    """ชาร์ตของคำถามหนึ่ง หรือข้อความบอกว่าทำไมไม่มีชาร์ต

    lang คือภาษาของข้อความ โหมด AI ส่งภาษาที่ผู้ใช้พิมพ์มา เพราะคำถามที่โมเดลเขียนเป็นอังกฤษเสมอ
    """
    if mario.asked(prompt):
        return Reply(None, kind="mario")
    found = spot.lookup(prompt, memory=memory)
    if found is None:
        return Reply(None, MISSING[lang or spot.language_of(prompt)], kind="not_found")
    lang = lang or found.lang
    # ตอบแค่ push/fold ที่แก้สด นอกนั้นบอกว่ายังไม่มี แต่ยังจำตำแหน่งกับสแตกไว้ถามต่อได้
    seat = pushfold_chart.seat_problem(found.request) if pushfold_chart.applies(found.request) else None
    if seat:
        return Reply(found, seat_message(seat, lang), kind="seat_not_at_table")
    problem = pushfold_chart.payout_problem(found.request) if pushfold_chart.applies(found.request) else None
    if problem:
        return Reply(found, BAD_PAYOUTS[lang].format(why=problem), kind="bad_payouts")
    if pushfold_chart.applies(found.request) and pushfold_chart.all_in_by_posting(found.request):
        return Reply(found, ALL_IN_BY_POSTING[lang], kind="all_in_by_posting")
    made = pushfold_chart.solved(found.request) if pushfold_chart.applies(found.request) else None
    if made is None:
        return Reply(found, PUSH_FOLD_ONLY[lang], kind="push_fold_only")
    return Reply(dataclasses.replace(found, book=made.book, chart=made.chart), note=made.note)



def seat_message(problem: "pushfold_chart.SeatProblem", lang: str) -> str:
    """บอกว่าไม่มีตำแหน่งนี้เพราะอะไร แล้วบอกวิธีแก้คำถาม"""
    players, stage = len(problem.seats), problem.stage
    facts = ({"entrants": stage.entrants, "paid": stage.paid, "left": stage.left} if stage else {})
    why = SEAT_WHY[lang][problem.source].format(**facts)
    said = SEAT_NOT_AT_TABLE[lang].format(players=players, why=why, seat=problem.seat,
                                          seats=", ".join(problem.seats))
    fix = SEAT_FIX[lang].format(first=problem.seats[0], players=players)
    if problem.fits and problem.source != "aof":
        size = "stage" if problem.source in ("bubble", "left") else "table"
        fix += SEAT_FIX_SIZE[lang][size].format(fits=problem.fits)
    return f"{said}\n{fix}"

def answer(prompt: str, color: bool, memory=None) -> tuple[str, "spot.Spot | None"]:
    """ข้อความที่จะพิมพ์ในเทอร์มินัลให้หนึ่งคำถาม กับ spot ที่เจอไว้ใช้เป็นความจำตาถัดไป"""
    return render(reply(prompt, memory=memory), color)


def ai_answer(prompt: str, color: bool, history: tuple = (),
              memory=None) -> tuple[str, "spot.Spot | None", tuple]:
    """โหมด AI: ข้อความคุย คำถามที่ AI เขียน แล้วชาร์ต คืนประวัติคุยใหม่ด้วย"""
    made = assistant.answer(prompt, reply, history, memory)
    lines = [made.say]
    if made.query:
        lines.append(assistant.QUERY_LINE.format(query=made.query))
    found = None
    if made.made is not None:
        shown, found = render(made.made, color)
        lines += ["", shown]
    return "\n".join(lines), found, made.history


def render(made: Reply, color: bool) -> tuple[str, "spot.Spot | None"]:
    if made.kind == "mario":
        return mario.render(color), None
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
            # context แบบ spot ให้ตัวถอดเสียงเขียนชื่อตำแหน่งเป็นอังกฤษ ตัวอ่านจะได้อ่านออก
            self._listener = soniox_rt.LiveListener(soniox_api.load_api_key(),
                                                    device=self._device, meter=self._meter,
                                                    context="spot")
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
    memory, ai, history = None, not args.ai_off, ()
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
            memory, history = None, ()
        elif kind == "typed" and assistant.toggle(text) is not None:
            ai = assistant.toggle(text)
            print(f"\n{assistant.TURNED[ai]}")
        elif kind == "typed" and text.lower() in CONTACT_COMMANDS:
            print(f"\n{CONTACT}\n{COPYRIGHT}")
        elif kind == "typed" and help_for(text):
            print(f"\n{help_for(text)}")
        elif text:
            if kind == "heard":
                print(f"\n> {text}")
            if ai:
                shown, found, history = ai_answer(text, color, history, memory)
            else:
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
    parser.add_argument("--ai-off", action="store_true", help="โหมดพื้นฐาน ไม่ผ่าน AI")
    args = parser.parse_args()
    if args.prompt:
        color = sys.stdout.isatty()
        print(answer(args.prompt, color)[0] if args.ai_off else ai_answer(args.prompt, color)[0])
        return 0
    try:
        return run(args)
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
