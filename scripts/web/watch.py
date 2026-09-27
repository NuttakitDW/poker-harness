"""ดูคำถามที่คนถามบนเว็บ tamkwai.com ในเทอร์มินัล แบบเดียวกับที่บอท Discord พิมพ์ข้อความเข้ามา

ดึง log ของ Vercel ด้วย vercel logs ทุก POLL_SECONDS วินาที พิมพ์คำถามใหม่ แล้วเก็บลง
tmp/logs/web-YYYYMMDD.jsonl เพราะ Vercel Hobby เก็บ log ไว้แค่ชั่วโมงเดียว
ไฟล์ที่เก็บไว้เปิดดูคำถามที่พลาดด้วย make web-review

ไม่ใช้ log สด (runtime-logs stream) เพราะทดสอบแล้วทำบรรทัดหายตอนต่อสายและตอนถูกตัดทุก 5 นาที
log ย้อนหลังครบกว่า แค่ช้ากว่าราว 15-25 วินาที เปิดครั้งแรกดึงคำถามย้อนหลัง 1 ชั่วโมง
คำถามที่ถามตอนปิดเครื่องจึงไม่หาย (ถ้าเปิดภายในชั่วโมง) และไม่ถูกเก็บซ้ำแม้เปิดใหม่ กด Ctrl+C เพื่อออก

ต้อง login Vercel CLI ไว้ (vercel login) และ link โปรเจกต์แล้ว (.vercel/project.json)

ใช้:
    make web-watch
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import json
import math
import pathlib
import subprocess
import sys
import time
from typing import Callable, Iterable, TextIO

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))

import question_log  # noqa: E402

DOMAIN = "tamkwai.com"
PREFIX = "web"
POLL_SECONDS = 10
HISTORY_LIMIT = 1000  # คำขอต่อการดึงหนึ่งครั้ง
FIRST_HISTORY = "1h"  # Vercel Hobby เก็บ log ไว้เท่านี้
COLORS = {"chart": "32", "talk": "36", "error": "31", "start": "2", "dim": "2"}
HELLO = f"ตามควายเว็บ: ดูคำถามจาก {DOMAIN} ช้ากว่าจริงราว 20 วินาที เก็บไว้ที่ tmp/logs/web-*.jsonl (Ctrl+C ออก)"


class FetchError(RuntimeError):
    """ดึง log จาก vercel logs ไม่ได้ ข้อความบอกว่าเพราะอะไร"""


@dataclasses.dataclass(frozen=True)
class Event:
    """หนึ่งบรรทัดที่น่าดู kind คือ question, error หรือ start (เครื่องเปิดใหม่)"""

    kind: str
    when: datetime.datetime
    row: str
    text: str
    entry: dict | None = None

    @property
    def key(self) -> str:
        """คำถามเดียวกันจากการดึงคนละรอบใช้เวลาของเซิร์ฟเวอร์กับตัวคำถามจับซ้ำ ไฟล์เก่าก็ใช้ key นี้"""
        if self.entry is None:
            return self.row
        return question_key(self.entry.get("at"), self.text)


def question_key(server_at: object, question: object) -> str:
    return f"{server_at}|{question}"


def read(raw: str) -> Event | None:
    """หนึ่งบรรทัด log เป็น Event หรือ None ถ้าไม่ใช่สิ่งที่อยากดู เช่น access log ของทุก request"""
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(record, dict) or not isinstance(record.get("message"), str):
        return None
    message = record["message"].strip()
    when = datetime.datetime.fromtimestamp(record.get("timestampInMs", time.time() * 1000) / 1000)
    row = str(record.get("rowId", message))
    if message.startswith("{"):
        try:
            entry = json.loads(message)
        except ValueError:
            entry = None
        if isinstance(entry, dict) and "question" in entry:
            return Event("question", when, row, entry["question"], entry)
    if "cold start" in message:
        return Event("start", when, row, message)
    if record.get("level") in ("error", "fatal") or message.startswith("Traceback"):
        return Event("error", when, row, message)
    return None


def _paint(text: str, code: str | None, color: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if color and code else text


def show(event: Event, color: bool = True) -> str:
    """บรรทัดที่พิมพ์ในเทอร์มินัล"""
    clock = event.when.strftime("%H:%M:%S")
    if event.kind != "question":
        return _paint(f"{clock}  {event.kind:<10} {event.text}", COLORS.get(event.kind), color)
    entry = event.entry or {}
    kind = str(entry.get("kind", "?"))
    mark = "[รูป] " if entry.get("source") == "image" else ""
    lines = [f"{clock}  {_paint(f'{kind:<10}', COLORS.get(kind, '33'), color)} {mark}{event.text}"]
    query = entry.get("ai_query")
    if query and query != event.text:
        lines.append(_paint(f"{'':20} AI → {query}", COLORS["dim"], color))
    return "\n".join(lines)


class Seen:
    """บรรทัดที่เห็นแล้ว การดึงแต่ละรอบทับช่วงเวลากัน จำไว้แค่ limit ตัวล่าสุด"""

    def __init__(self, limit: int = 5000) -> None:
        self._order: collections.deque[str] = collections.deque()
        self._rows: set[str] = set()
        self._limit = limit

    @classmethod
    def from_files(cls, folder: pathlib.Path, days: int = 2) -> "Seen":
        """คำถามที่รอบก่อนเก็บไว้แล้วในไฟล์ของ days วันล่าสุด เปิดใหม่แล้วดึงย้อนหลังจะได้ไม่เก็บซ้ำ"""
        seen = cls()
        for path in sorted(folder.glob(f"{PREFIX}-*.jsonl"))[-days:]:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and "server_at" in row:
                    seen.first(question_key(row["server_at"], row.get("question")))
        return seen

    def first(self, row: str) -> bool:
        if row in self._rows:
            return False
        self._order.append(row)
        self._rows.add(row)
        while len(self._order) > self._limit:
            self._rows.discard(self._order.popleft())
        return True


def save(event: Event, folder: pathlib.Path) -> None:
    """เก็บคำถามลงไฟล์ของวันนั้น at เป็นเวลาที่ Vercel จดตามเขตเวลาของเครื่องนี้
    server_at คือเวลาของเซิร์ฟเวอร์ (UTC) ไว้จับคำถามซ้ำ"""
    entry = dict(event.entry or {})
    entry["server_at"] = entry.pop("at", None)
    question_log.record(entry, when=event.when, folder=folder, prefix=PREFIX)


def consume(lines: Iterable[str], seen: Seen, folder: pathlib.Path, out: TextIO, color: bool,
            questions_only: bool = False) -> int:
    """พิมพ์และเก็บทุกบรรทัดที่น่าดู คืนจำนวนคำถามที่เก็บ
    questions_only ใช้กับของย้อนหลัง error กับเครื่องเปิดใหม่ที่ผ่านไปแล้วไม่ต้องพิมพ์"""
    count = 0
    for raw in lines:
        event = read(raw)
        if event is None or (questions_only and event.kind != "question") or not seen.first(event.key):
            continue
        if event.kind == "question":
            try:
                save(event, folder)
                count += 1
            except OSError as error:
                print(f"เก็บคำถามไม่ได้: {error}", file=out, flush=True)
        print(show(event, color), file=out, flush=True)
    return count


def history_lines(raw: str) -> list[str]:
    """หนึ่งแถวของ vercel logs --json (หนึ่งคำขอ) เป็นบรรทัด log ทีละบรรทัด"""
    try:
        row = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(row, dict):
        return []
    logs = row.get("logs") if isinstance(row.get("logs"), list) else [row]
    return [json.dumps({"level": log.get("level"), "message": log.get("message"),
                        "rowId": f"{row.get('id')}:{index}",
                        "timestampInMs": log.get("timestamp") or row.get("timestamp")},
                       ensure_ascii=False)
            for index, log in enumerate(logs) if isinstance(log, dict)]


def _run_cli(args: list[str]) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120, check=True).stdout


def backfill(since: str, run: Callable[[list[str]], str] = _run_cli, questions: bool = True) -> list[str]:
    """log ย้อนหลัง since (เช่น 1h, 2m) จาก vercel logs เรียงเก่าไปใหม่
    questions=False ดึงทุกคำขอ จะได้เห็น error กับเครื่องเปิดใหม่ด้วย"""
    args = ["vercel", "logs", "--environment", "production", "--no-branch", "--json",
            "--since", since, "--limit", str(HISTORY_LIMIT)]
    if questions:
        args += ["--query", "question"]
    try:
        output = run(args)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip().splitlines()
        raise FetchError(detail[-1] if detail else f"vercel logs จบด้วยรหัส {error.returncode}") from None
    except (OSError, subprocess.SubprocessError) as error:
        raise FetchError(f"เรียก vercel ไม่ได้ ({error}) ติดตั้งด้วย npm i -g vercel") from None
    rows = []
    for raw in output.splitlines():
        try:
            rows.append((json.loads(raw).get("timestamp", 0), raw))
        except (ValueError, AttributeError):
            continue
    return [line for _, raw in sorted(rows, key=lambda pair: pair[0]) for line in history_lines(raw)]


def _since(gap_seconds: float) -> str:
    """ช่วงที่ต้องดึง นับจากการดึงที่สำเร็จครั้งล่าสุด บวกอีกนาทีเผื่อ log ที่เข้าช้า (ราว 16 วินาที)
    อย่างน้อย 2 นาที อย่างมาก 60 นาทีซึ่งเป็นทั้งหมดที่ Vercel Hobby เก็บไว้"""
    return f"{min(60, max(2, math.ceil(gap_seconds / 60) + 1))}m"


def follow(folder: pathlib.Path = question_log.LOG_DIR, out: TextIO = sys.stdout,
           run: Callable[[list[str]], str] = _run_cli, sleep: Callable[[float], None] = time.sleep,
           clock: Callable[[], float] = time.time) -> None:
    """ดึงไปเรื่อย ๆ จนกด Ctrl+C ดึงไม่ได้ก็บอกครั้งเดียวแล้วลองใหม่รอบหน้า"""
    color = out.isatty()
    seen = Seen.from_files(folder)
    print(HELLO, file=out, flush=True)
    since, questions, last_ok, problem = FIRST_HISTORY, True, None, None
    while True:
        try:
            lines = backfill(since, run, questions)
            caught = consume(lines, seen, folder, out, color, questions_only=questions)
            if questions:
                print(_paint(f"ย้อนหลัง {since}: คำถามที่ยังไม่มี {caught} ข้อ รอคำถามใหม่…", COLORS["dim"], color),
                      file=out, flush=True)
            if problem is not None:
                print(_paint("ดึง log ได้แล้ว", COLORS["dim"], color), file=out, flush=True)
            last_ok, questions, problem = clock(), False, None
        except FetchError as error:
            if str(error) != problem:
                print(_paint(f"ดึง log ไม่ได้: {error}", COLORS["error"], color), file=out, flush=True)
            problem = str(error)
        sleep(POLL_SECONDS)
        if last_ok is not None:
            since = _since(clock() - last_ok)


def main() -> int:
    try:
        follow()
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
