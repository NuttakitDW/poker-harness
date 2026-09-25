"""วัดว่าตัวอ่านคำถาม spot อ่านถูกแค่ไหน บนชุดคำถามจริงที่มีเฉลย

ชุดคำถามอยู่ที่ tests/fixtures/spot/questions.jsonl หนึ่งบรรทัดต่อหนึ่งคำถาม
    {"question": ..., "source": "discord-voice" | "session" | "synthetic",
     "expected": {ฟิลด์ที่ต้องอ่านได้}, "known_gap": "ทำไมยังอ่านไม่ได้" (ถ้ามี)}
ตรวจเฉพาะฟิลด์ที่ใส่ไว้ใน expected ฟิลด์ที่ไม่ใส่ถือว่าไม่สนใจ

known_gap คือคำถามที่รู้ว่ายังพลาด ไม่นับว่าพัง ถ้าวันหนึ่งผ่านแล้ว test จะเตือนให้เอาป้ายออก
คำถามที่พลาดจาก Discord (make bot-review) ใส่เฉลยแล้วต่อท้ายไฟล์นี้ได้เลย

ใช้:
    make spot-eval
    .venv/bin/python scripts/voice/spot_eval.py --failures
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
from typing import Callable

import preflop

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "fixtures" / "spot" / "questions.jsonl"
FIELDS = ("hero", "stack", "shovers", "players", "ante", "ante_mode", "hands")
UNORDERED = ("shovers", "hands")
STACK_TOLERANCE = 1e-9

Reader = Callable[[str], dict]


def empty() -> dict:
    return {field: None for field in FIELDS} | {"shovers": [], "hands": []}


def regex_reader(question: str) -> dict:
    """สิ่งที่ตัวอ่าน regex อ่านได้จากคำถามเดียว ไม่มีความจำจากตาก่อน

    คู่มือคนเดียวนับเป็นคนแจม แบบเดียวกับที่ pushfold_chart ใช้แก้ชาร์ต
    """
    request = preflop.parse(question)
    shovers = list(request.shovers) or ([request.villain] if request.villain else [])
    return {"hero": request.hero, "stack": request.stack, "shovers": shovers,
            "players": request.players, "ante": request.ante, "ante_mode": request.ante_mode,
            "hands": preflop.hands_in(question)}


def _same(field: str, want, got) -> bool:
    if field in UNORDERED:
        return sorted(want or []) == sorted(got or [])
    if field in ("stack", "ante") and want is not None and got is not None:
        return abs(float(want) - float(got)) < STACK_TOLERANCE
    return want == got


def check(expected: dict, read: dict) -> dict[str, bool]:
    """ถูกหรือผิดของแต่ละฟิลด์ที่มีเฉลย"""
    return {field: _same(field, want, read.get(field)) for field, want in expected.items()}


@dataclasses.dataclass(frozen=True)
class Row:
    case: dict
    read: dict
    marks: dict

    @property
    def passed(self) -> bool:
        return all(self.marks.values())

    @property
    def failed_fields(self) -> dict:
        return {field: {"want": self.case["expected"][field], "got": self.read.get(field)}
                for field, ok in self.marks.items() if not ok}


@dataclasses.dataclass(frozen=True)
class Result:
    rows: tuple[Row, ...]

    @property
    def passed(self) -> int:
        return sum(row.passed for row in self.rows)

    @property
    def fields(self) -> dict[str, tuple[int, int]]:
        """(ถูก, ทั้งหมด) ของแต่ละฟิลด์ นับเฉพาะคำถามที่มีเฉลยฟิลด์นั้น"""
        counts = {}
        for field in FIELDS:
            marks = [row.marks[field] for row in self.rows if field in row.marks]
            if marks:
                counts[field] = (sum(marks), len(marks))
        return counts

    def render(self, failures_only: bool = False) -> str:
        total = len(self.rows)
        lines = [f"อ่านถูกทั้งข้อ {self.passed}/{total} ({self.passed / total:.0%})"]
        for source in dict.fromkeys(row.case.get("source", "?") for row in self.rows):
            group = [row for row in self.rows if row.case.get("source", "?") == source]
            lines.append(f"  {source:14} {sum(r.passed for r in group)}/{len(group)}")
        lines.append("ต่อฟิลด์:")
        for field, (right, count) in self.fields.items():
            lines.append(f"  {field:10} {right}/{count}")
        shown = [row for row in self.rows if not (failures_only and row.passed)]
        if shown:
            lines.append("")
        for row in shown:
            mark = "ok  " if row.passed else ("gap " if row.case.get("known_gap") else "FAIL")
            lines.append(f"{mark} [{row.case.get('source', '?')}] {row.case['question']}")
            for field, detail in row.failed_fields.items():
                lines.append(f"       {field}: ต้องได้ {detail['want']} แต่ได้ {detail['got']}")
        return "\n".join(lines)


def load(path: pathlib.Path = CORPUS) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(cases: list[dict], reader: Reader = regex_reader) -> Result:
    rows = []
    for case in cases:
        read = reader(case["question"])
        rows.append(Row(case, read, check(case["expected"], read)))
    return Result(tuple(rows))


def main() -> int:
    parser = argparse.ArgumentParser(description="วัดความแม่นของตัวอ่านคำถาม spot")
    parser.add_argument("--corpus", type=pathlib.Path, default=CORPUS)
    parser.add_argument("--failures", action="store_true", help="แสดงเฉพาะข้อที่พลาด")
    args = parser.parse_args()
    print(evaluate(load(args.corpus)).render(failures_only=args.failures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
