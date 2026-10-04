"""ตามควายเวอร์ชันเว็บ ส่วนที่ไม่ขึ้นกับ HTTP: ถามชาร์ต อ่านรูปโต๊ะ ความจำของแต่ละคน และจำกัดความถี่

ใช้ solver, AI และตัวอ่านรูปชุดเดียวกับบอท Discord ต่างกันแค่ความจำอยู่ที่เบราว์เซอร์ (state.py) แทนคนกับห้อง
ของที่เรียกออกไปข้างนอกทั้งหมดอยู่ใน Tools เพื่อให้ test แทนด้วยของปลอมได้
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import functools
import json
import os
import pathlib
import sys
import threading
import time
import traceback
from typing import Callable

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS / "voice"))
sys.path.insert(0, str(SCRIPTS / "discord_bot"))

import analytics  # noqa: E402
import assistant  # noqa: E402
import chart_image  # noqa: E402
import keys  # noqa: E402
import mario  # noqa: E402
import plo_type  # noqa: E402
import question_log  # noqa: E402
import spot_chart  # noqa: E402
import table_image  # noqa: E402

FAILED = "ขอโทษ ทำชาร์ตไม่สำเร็จ ลองถามใหม่อีกทีนะ"
NOT_READ = "อ่านรูปนี้เป็นโต๊ะไม่ออก ลองแคปจอให้เห็นทั้งโต๊ะ หรือพิมพ์มาแทนนะ"
NO_VISION = "ตอนนี้ยังอ่านรูปไม่ได้ พิมพ์คำถามมาแทนนะ"
FORGOT = "ลืม spot เดิมแล้ว ถามใหม่ได้เลย"
EMPTY = "พิมพ์คำถามก่อนนะ เช่น BTN shove 10bb"
TOO_LONG = "คำถามยาวเกินไป ย่อให้เหลือตำแหน่งกับสแตกก็พอ"
MAX_QUESTION_CHARS = 500
MAX_IMAGE_BYTES = 10_000_000
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
# ข้อความของบอทบอกให้พิมพ์ /ai-off ซึ่งหน้าเว็บไม่มี หน้าเว็บใช้สวิตช์แทน
TURNED = {
    True: "เปิดโหมด AI แล้ว คุยได้ตามสบาย เดี๋ยวแปลงเป็นคำถามชาร์ตให้",
    False: "ปิดโหมด AI แล้ว พิมพ์คำถามแบบสั้นตรง ๆ เช่น BB vs BTN shove 10bb",
}
PLACE = {"server": "web", "channel": None}  # ตั้งใจไม่เก็บว่าใครถาม เหมือนบันทึกของ Discord


@dataclasses.dataclass(frozen=True)
class Session:
    """ความจำของผู้ใช้หนึ่งคน memory คือ spot ล่าสุด history คือบทสนทนากับ AI"""

    memory: object = None
    history: tuple = ()
    ai: bool = True


@dataclasses.dataclass(frozen=True)
class Result:
    """คำตอบหนึ่งครั้ง lines คือข้อความ chart คือรูป PNG ถ้ามี"""

    lines: tuple[str, ...]
    kind: str
    chart: bytes | None = None
    plo: dict | None = None
    plo_fallback: str | None = None


@functools.cache
def _message_store():
    return analytics.store_from_env()


def _store_message(entry: dict) -> None:
    """เก็บคำถามลงฐานข้อมูลของหน้า dashboard ด้วย (ถ้าตั้ง DATABASE_URL หรือ ANALYTICS_DB) พังก็ไม่กระทบคำตอบ"""
    store = _message_store()
    if store is None:
        return
    try:
        analytics.save_message(store, analytics.message_row(entry, channel=str(entry.get("server") or "web"),
                                                            now=time.time()))
    except Exception as error:  # noqa: BLE001 - the answer matters more than the record
        print(f"เก็บคำถามลงฐานข้อมูลไม่ได้: {error}", flush=True)


def _record(line: dict) -> None:
    """จดลงไฟล์เหมือนบอท Discord บน Vercel ดิสก์เขียนไม่ได้ ตั้ง WEB_LOG=stdout ให้ไปอยู่ใน log ของ Vercel"""
    entry = question_log.entry(**line)
    _store_message(entry)
    if os.environ.get("WEB_LOG") == "stdout":
        at = datetime.datetime.now().isoformat(timespec="seconds")
        print(json.dumps({"at": at, **entry}, ensure_ascii=False, default=str), flush=True)
        return
    question_log.record(entry)


def _read_question(data: bytes, mime: str, key: str) -> str:
    return table_image.question(table_image.read(data, mime, key))


@dataclasses.dataclass(frozen=True)
class Tools:
    solve: Callable = spot_chart.reply
    answer: Callable = assistant.answer
    render: Callable = chart_image.render
    mario: Callable = mario.png
    read_question: Callable = _read_question
    vision_key: Callable = lambda: keys.find(*table_image.KEY_NAMES)
    log: Callable = _record
    place: dict = dataclasses.field(default_factory=lambda: dict(PLACE))  # ที่มาที่จดลงบันทึก บอท / ของ Discord ใช้ของตัวเอง


def invalid_question(question: str) -> str | None:
    """ข้อความบอกว่าทำไมคำถามนี้ใช้ไม่ได้ หรือ None ถ้าใช้ได้"""
    if not question.strip():
        return EMPTY
    if len(question) > MAX_QUESTION_CHARS:
        return TOO_LONG
    return None


def accepts_image(mime: str) -> bool:
    return mime in IMAGE_TYPES


def forget(session: Session) -> Session:
    return Session(ai=session.ai)


def toggle_ai(session: Session, on: bool) -> tuple[str, Session]:
    """เปิดหรือปิด AI ปิดแล้วลืมบทสนทนาด้วย เหมือน !ai-off ใน Discord"""
    history = session.history if on else ()
    return TURNED[on], dataclasses.replace(session, ai=on, history=history)


def _think(question: str, session: Session, tools: Tools, ai: bool) -> tuple[object, list[str], Session, dict]:
    """(ผลจาก solver หรือ None, ข้อความของ AI, ความจำใหม่, ช่องเพิ่มในบันทึก)"""
    if not ai or not session.ai:
        return tools.solve(question, memory=session.memory), [], session, {}
    result = tools.answer(question, tools.solve, session.history, session.memory)
    lines = [result.say]
    if result.query and result.query != question:
        lines.append(assistant.QUERY_LINE.format(query=result.query))
    return result.made, lines, dataclasses.replace(session, history=result.history), {"ai_query": result.query}


def _log(tools: Tools, question: str, source: str, kind: str, request=None, **fields) -> None:
    """จดคำถามลงบันทึก พังก็แค่เตือน ไม่ให้การจดทำให้ตอบไม่ได้"""
    try:
        tools.log({"question": question, "source": source, "kind": kind, "request": request,
                   **tools.place, **fields})
    except OSError as error:
        print(f"จดบันทึกคำถามไม่ได้: {error}", flush=True)


MAX_REPLY_LOG_CHARS = 2_000


def reply_text(result: Result) -> str:
    """What the visitor saw, as plain text for the log: the AI's words, the answer lines, and a
    marker for a chart image."""
    parts = list(result.lines)
    if result.plo_fallback and result.plo_fallback not in parts:
        parts.append(result.plo_fallback)
    if result.chart:
        parts.append("[chart image]")
    return "\n".join(parts)[:MAX_REPLY_LOG_CHARS]


def ask(question: str, session: Session, tools: Tools, ai: bool = True,
        heard: str | None = None, source: str = "text") -> tuple[Result, Session]:
    """ตอบคำถามหนึ่งข้อ คืนคำตอบกับความจำใหม่ พังตรงไหนก็ได้คำขอโทษและความจำเดิม"""
    try:
        made, said, after, logged = _think(question, session, tools, ai)
        result, after = _present(made, tuple(filter(None, (heard, *said))), after, tools)
        request = made.found.request if made is not None and made.found else None
        _log(tools, question, source, result.kind, request, reply=reply_text(result), **logged)
        return result, after
    except Exception as error:  # noqa: BLE001 เว็บต้องไม่ตายเพราะคำถามเดียว
        traceback.print_exc()
        _log(tools, question, source, "error", error=repr(error), reply=FAILED)
        return Result((FAILED,), "error"), session


def _present(made, lines: tuple[str, ...], after: Session, tools: Tools) -> tuple[Result, Session]:
    """The visitor's answer for one solver reply (None: the AI only talked)."""
    if made is None:
        return Result(lines, "talk"), after
    if made.found is not None:
        after = dataclasses.replace(after, memory=made.found.request)
    if made.kind == "mario":
        return Result(lines, made.kind, tools.mario()), after
    if made.kind == "plo_type" and getattr(made, "plo", None) and made.plo.hand:
        lang = "TH" if any("\u0e00" <= char <= "\u0e7f" for char in (made.message or "")) else "EN"
        fallback = made.message or plo_type.render(made.plo.hand, lang)
        return Result((*lines, fallback), made.kind,
                      plo=plo_type.presentation(made.plo.hand, lang),
                      plo_fallback=fallback), after
    if made.message is not None:
        return Result((*lines, made.message), made.kind), after
    found = made.found
    png = tools.render(found.book, found.chart, found.hands, found.lang, (made.note,))
    return Result(lines, made.kind, png), after


def ask_image(data: bytes, mime: str, extra: str | None, session: Session,
              tools: Tools) -> tuple[Result, Session]:
    """อ่านรูปโต๊ะเป็นคำถาม แล้วถามชาร์ตโหมดพื้นฐาน ข้อความที่แนบมาต่อท้ายคำถาม"""
    key = tools.vision_key()
    if not key:
        return Result((NO_VISION,), "no_vision"), session
    try:
        read = tools.read_question(data, mime, key)
    except Exception:  # noqa: BLE001 อ่านรูปพังก็ต้องตอบ ไม่ใช่เงียบหาย
        traceback.print_exc()
        _log(tools, "", "image", "not_read")
        return Result((NOT_READ,), "not_read"), session
    question = " ".join(filter(None, (read, extra)))
    # รูปคือ spot ใหม่ทั้งโต๊ะ ไม่ยืมตำแหน่งหรือคนที่ all-in จากคำถามก่อน
    fresh = dataclasses.replace(session, memory=None)
    return ask(question, fresh, tools, ai=False, heard=f"อ่านจากรูปได้ว่า: {question}", source="image")


class RateLimit:
    """แต่ละคนถามได้ per_window ครั้งต่อ window วินาที กันคนยิงถามจนค่า AI บาน"""

    def __init__(self, per_window: int = 12, window: float = 60.0) -> None:
        self._per_window = per_window
        self._window = window
        self._seen: dict[str, collections.deque] = {}
        self._lock = threading.Lock()

    def allow(self, who: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            times = self._seen.setdefault(who, collections.deque())
            while times and now - times[0] >= self._window:
                times.popleft()
            if len(times) >= self._per_window:
                return False
            times.append(now)
            return True
