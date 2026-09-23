"""สร้างโน้ตเว็บ PLO จากแบบฝึกหัดบน nuttakitkundum.com

ข้อมูลของทั้งสามหน้าอยู่ในสคริปต์ของหน้า HTML ใน cfr-kuhn-animation
จึงให้ node ประเมินส่วนข้อมูลแล้วส่ง JSON กลับมา แล้วแบ่งเป็นโน้ตสั้น ๆ
ให้แต่ละโน้ตพอดีกับงบ MAX_PAGE_CHARS ของ brain.py ผู้ช่วยเสียงจะได้เลือกโน้ตที่ตรงคำถาม

    python scripts/build_plo_notes.py [--site ../cfr-kuhn-animation]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import html
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "harnesses" / "EN" / "sources" / "web"
DEFAULT_SITE = ROOT.parent / "cfr-kuhn-animation"
SITE_URL = "https://www.nuttakitkundum.com"
PREFIX = "plo-"
# เผื่อหัวโน้ตไว้ราว 400 ตัวอักษร ให้ทั้งโน้ตไม่เกิน MAX_PAGE_CHARS = 2200 ของ brain.py
BODY_BUDGET = 1750

SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

# ประเมินเฉพาะส่วนประกาศข้อมูลของสคริปต์หน้าเว็บ ตัดก่อนโค้ดที่แตะ DOM
DUMP_JS = r"""
const fs = require('fs'); const vm = require('vm');
const [file, names] = process.argv.slice(1);
const page = fs.readFileSync(file, 'utf8');
const script = [...page.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).find(s => s.includes('PRIMER'));
const stops = [/^(const|let) (tabBtns|MODES)\b/m, /^.*document\./m]
  .map(r => script.search(r)).filter(i => i >= 0);
const code = script.slice(0, Math.min(...stops)).replace(/^(const|let) /gm, 'var ');
const ctx = { localStorage: { getItem: () => null } };
vm.createContext(ctx); vm.runInContext(code, ctx);
const out = {}; for (const n of names.split(',')) out[n] = ctx[n];
process.stdout.write(JSON.stringify(out));
"""


@dataclasses.dataclass(frozen=True)
class Page:
    """หนึ่งหน้าบนเว็บและชื่อตัวแปรข้อมูลที่ต้องดึง"""

    slug: str
    title: str
    names: str


PAGES = (
    Page("plo-starting-hands", "PLO Starting Hands", "PRIMER,CLASSIFY,SITUATIONS,OPTSETS,TIER_OPTS"),
    Page("plo-situations", "PLO Post-Flop Situations", "PRIMER,QUIZ,OPT"),
    Page("plo-hilo", "PLO Hi/Lo Split", "PRIMER,QUIZ"),
)


def load(site: pathlib.Path, page: Page) -> dict:
    """ข้อมูลของหน้า ตามที่สคริปต์หน้าเว็บประกาศไว้"""
    source = site / f"{page.slug}.html"
    if not source.is_file():
        raise SystemExit(f"ไม่พบหน้า {source}")
    result = subprocess.run(["node", "-e", DUMP_JS, str(source), page.names],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"อ่านข้อมูล {source.name} ไม่สำเร็จ: {result.stderr.strip()}")
    return json.loads(result.stdout)


def th(value) -> str:
    """ข้อความภาษาไทยแบบไม่มีแท็ก HTML"""
    text = value.get("th", value.get("en", "")) if isinstance(value, dict) else str(value or "")
    text = re.sub(r"<br\s*/?>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def hand(cards: str) -> str:
    """แปลง AsAcKdKh เป็น A♠A♣K♦K♥ (AAKK double-suited) ให้ค้นด้วยอันดับไพ่ได้"""
    clean = re.sub(r"\s+", "", cards)
    pairs = [(clean[i], clean[i + 1].lower()) for i in range(0, len(clean) - 1, 2)]
    shown = "".join(rank + SUITS.get(suit, suit) for rank, suit in pairs)
    if len(pairs) != 4:
        return shown
    counts = sorted((sum(1 for _, s in pairs if s == suit) for suit in {s for _, s in pairs}), reverse=True)
    shape = {(2, 2): "double-suited", (4,): "monotone", (1, 1, 1, 1): "rainbow"}.get(
        tuple(counts), "single-suited" if counts[0] >= 2 else "rainbow")
    return f"{shown} ({''.join(rank for rank, _ in pairs)} {shape})"


def primer_blocks(primer: list[dict]) -> list[str]:
    """หัวข้อพื้นฐานของหน้า แต่ละหัวข้อเป็นหนึ่งก้อน"""
    blocks = []
    for section in primer:
        lines = [f"### {th(section['h'])}"]
        lines += [th(p) for p in section.get("p", [])]
        lines += [f"- {th(item)}" for item in section.get("list", [])]
        for row in section.get("table", {}).get("rows", []):
            lines.append("- " + " — ".join(th(cell) for cell in row))
        if "callout" in section:
            lines.append(th(section["callout"]["text"]))
        blocks.append("\n".join(lines))
    return blocks


def classify_blocks(data: dict) -> list[str]:
    tiers = data["TIER_OPTS"]
    return [f"- มือ {hand(item['hand'])} → ระดับ {th(tiers[item['a']])}: {th(item['e'])}"
            for item in data["CLASSIFY"]]


def preflop_blocks(data: dict) -> list[str]:
    blocks = []
    for item in data["SITUATIONS"]:
        answer = th(data["OPTSETS"][item["os"]][item["a"]])
        blocks.append(f"- มือ {hand(item['hand'])} สถานการณ์: {th(item['ctx'])} → คำตอบ {answer}: {th(item['e'])}")
    return blocks


def postflop_blocks(data: dict) -> list[str]:
    blocks = []
    for item in data["QUIZ"]:
        answer = th(data["OPT"][item["o"]][item["a"]])
        board = f" board {hand(item['board'])}" if item.get("board") else " (ก่อน flop)"
        blocks.append(f"- มือ {hand(item['hole'])}{board} สถานการณ์: {th(item['ctx'])}"
                      f" → คำตอบ {answer}: {th(item['e'])}")
    return blocks


def hilo_blocks(data: dict) -> list[str]:
    blocks = []
    for item in data["QUIZ"]:
        cards = ""
        if item.get("hole"):
            cards += f" มือ {hand(item['hole'])}"
        if item.get("board"):
            cards += f" board {hand(item['board'])}"
        answer = th(item["opts"][item["a"]])
        blocks.append(f"- คำถาม:{cards} {th(item['q'])} → คำตอบ {answer}: {th(item['e'])}")
    return blocks


def chunk(blocks: list[str], budget: int = BODY_BUDGET) -> list[list[str]]:
    """รวมก้อนข้อความเป็นกลุ่มที่ไม่เกินงบ ก้อนเดียวที่ยาวเกินก็อยู่กลุ่มของมันเอง"""
    groups: list[list[str]] = []
    size = 0
    for block in blocks:
        if groups and size + len(block) <= budget:
            groups[-1].append(block)
            size += len(block) + 1
        else:
            groups.append([block])
            size = len(block)
    return groups


@dataclasses.dataclass(frozen=True)
class Note:
    slug: str
    heading: str
    page: Page
    evidence: str
    body: str

    def render(self, checked: str) -> str:
        return (f"# {self.heading}\n\n"
                f"Source: nuttakitkundum.com {self.page.title} (drills adapted from Jeff Hwang, "
                f"Pot-Limit Omaha Poker: The Big Play Strategy)\n"
                f"URL: {SITE_URL}/{self.page.slug}\n"
                f"Checked: {checked}\n"
                f"Evidence: {self.evidence}\n\n"
                f"{self.body}\n")


def notes_for(page: Page, data: dict) -> list[Note]:
    """โน้ตทั้งหมดของหน้าหนึ่ง: พื้นฐานก่อน แล้วตามด้วยโจทย์ที่แบ่งเป็นชุด"""
    sections: list[tuple[str, str, str, list[str]]] = [
        ("primer", "หลักพื้นฐาน", "Primer section of the drill page.", primer_blocks(data["PRIMER"])),
    ]
    if page.slug == "plo-starting-hands":
        sections += [
            ("classify", "จัดระดับมือเริ่มต้น", "Hand-tier classification drill with explanations.",
             classify_blocks(data)),
            ("preflop", "ตัดสินใจ preflop", "Preflop decision drill by position and action.",
             preflop_blocks(data)),
        ]
    elif page.slug == "plo-situations":
        sections.append(("spots", "สถานการณ์หลัง flop", "Post-flop decision drill from Hwang Chapter 6.",
                         postflop_blocks(data)))
    else:
        sections.append(("quiz", "แบบทดสอบ Hi/Lo", "Hi/Lo quiz from Hwang Chapter 9 principles.",
                         hilo_blocks(data)))

    notes = []
    for key, label, evidence, blocks in sections:
        groups = chunk(blocks)
        for index, group in enumerate(groups, start=1):
            suffix = f" ชุด {index}" if len(groups) > 1 else ""
            notes.append(Note(
                slug=f"{page.slug}-{key}-{index}",
                heading=f"{page.title} — {label}{suffix}",
                page=page,
                evidence=evidence,
                body="\n".join(group),
            ))
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=pathlib.Path, default=DEFAULT_SITE)
    parser.add_argument("--checked", default=datetime.date.today().isoformat())
    args = parser.parse_args()

    notes = [note for page in PAGES for note in notes_for(page, load(args.site, page))]
    for stale in OUT.glob(f"{PREFIX}*.md"):
        stale.unlink()
    for note in notes:
        (OUT / f"{note.slug}.md").write_text(note.render(args.checked), encoding="utf-8")
    for note in notes:
        print(f"{note.slug}.md\t{note.heading}")


if __name__ == "__main__":
    main()
