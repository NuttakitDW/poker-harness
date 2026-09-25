"""บันทึกทุกคำถามชาร์ตที่เข้ามาทาง Discord เป็น JSONL วันละไฟล์ ไว้หาประโยคที่ตัวอ่านยังอ่านไม่ออก

ไฟล์อยู่ที่ tmp/logs/discord-YYYYMMDD.jsonl ซึ่ง git ไม่เก็บ หนึ่งบรรทัดต่อหนึ่งคำถาม
เก็บคำถาม (ถ้าเป็นเสียงคือข้อความที่ถอดได้) ค่าที่ตัวอ่านได้ และชนิดคำตอบ
ไม่เก็บว่าใครถาม และลบไฟล์ที่เก่ากว่า KEEP_DAYS วันทิ้งทุกครั้งที่จด ตามที่บอกไว้ใน !privacy

ดูเฉพาะคำถามที่ไม่ได้ชาร์ต:
    .venv/bin/python scripts/discord_bot/question_log.py
    make bot-review
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "tmp" / "logs"
PATTERN = "discord-*.jsonl"
ANSWERED = "chart"
KEEP_DAYS = 90


def entry(question: str, source: str, kind: str, request=None, **fields) -> dict:
    """หนึ่งบรรทัดของบันทึก source คือ text หรือ voice, request คือ preflop.Request ที่อ่านได้"""
    parsed = dataclasses.asdict(request) if request is not None else None
    return {"question": question, "source": source, "kind": kind, "parsed": parsed, **fields}


def record(line: dict, when: datetime.datetime | None = None,
           folder: pathlib.Path = LOG_DIR) -> pathlib.Path:
    """ต่อท้ายไฟล์ของวันนั้น คืนพาธไฟล์"""
    when = when or datetime.datetime.now()
    folder.mkdir(parents=True, exist_ok=True)
    prune(folder, when.date())
    path = folder / f"discord-{when:%Y%m%d}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": when.isoformat(timespec="seconds"), **line},
                                ensure_ascii=False) + "\n")
    return path


def prune(folder: pathlib.Path = LOG_DIR, today: datetime.date | None = None) -> None:
    """ลบบันทึกที่เก่ากว่า KEEP_DAYS วัน ไฟล์ที่ชื่ออ่านวันที่ไม่ออกปล่อยไว้"""
    cutoff = (today or datetime.date.today()) - datetime.timedelta(days=KEEP_DAYS)
    for path in folder.glob(PATTERN):
        try:
            day = datetime.datetime.strptime(path.stem.removeprefix("discord-"), "%Y%m%d").date()
        except ValueError:
            continue
        if day < cutoff:
            path.unlink(missing_ok=True)


def misses(folder: pathlib.Path = LOG_DIR) -> list[dict]:
    """ทุกคำถามที่ไม่ได้ชาร์ต เรียงตามเวลา ข้ามบรรทัดที่อ่านไม่ได้"""
    found = []
    for path in sorted(folder.glob(PATTERN)):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") != ANSWERED:
                found.append(row)
    return found


def review(rows: list[dict]) -> str:
    """รายการคำถามที่พลาด แยกตามชนิด พร้อมค่าที่ตัวอ่านได้ ไว้เอาไปทำ test"""
    if not rows:
        return "ไม่มีคำถามที่พลาด"
    lines = []
    for kind in dict.fromkeys(row["kind"] for row in rows):
        group = [row for row in rows if row["kind"] == kind]
        lines.append(f"\n== {kind} ({len(group)})")
        for row in group:
            parsed = row.get("parsed") or {}
            seen = ", ".join(f"{key}={value}" for key, value in parsed.items()
                             if value not in (None, (), [], False))
            lines.append(f"  {row['at']}  [{row.get('source', '?')}]  {row['question']}")
            lines.append(f"      อ่านได้: {seen or 'ไม่ได้อะไรเลย'}")
    return "\n".join(lines).lstrip("\n")


def main() -> int:
    print(review(misses()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
