"""โหลดการ์ดหัวข้อและหน้าต้นฉบับที่การ์ดอ้างถึง

การ์ดหัวข้อมีส่วน "หน้าต้นฉบับ" ที่ชี้ไปยังหน้า PDF ที่เกี่ยวข้องอยู่แล้ว
จึงใช้การ์ดเป็นตารางนำทางแทนการสร้างดัชนี embedding ทั้งคลัง
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
HARNESSES = ROOT / "harnesses"
LANGUAGES = ("TH", "EN")

_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_PAGE_HEADING = re.compile(r"^## PDF page (\d+)\s*$", re.MULTILINE)
_CITATION_HEADINGS = ("## หน้าต้นฉบับ", "## Source pages")
_REQUIRES = re.compile(r"^- Requires: (.+)$", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class Citation:
    """ลิงก์หนึ่งรายการจากการ์ดไปยังหน้าต้นฉบับ"""

    label: str
    path: pathlib.Path
    page: int | None


@dataclasses.dataclass(frozen=True)
class Card:
    """การ์ดหัวข้อหนึ่งใบพร้อมรายการหน้าที่อ้างถึง"""

    language: str
    slug: str
    title: str
    body: str
    citations: tuple[Citation, ...]
    # คำใดคำหนึ่งต้องอยู่ในคำถาม การ์ดนี้จึงถูกเลือกได้ ว่างไว้คือไม่มีเงื่อนไข
    requires: tuple[str, ...] = ()

    @property
    def identifier(self) -> str:
        return f"{self.language}/{self.slug}"


def _section(text: str, headings: tuple[str, ...]) -> str:
    """เนื้อหาใต้หัวข้อแรกที่ตรง จนกว่าจะถึงหัวข้อระดับเดียวกันถัดไป"""
    for heading in headings:
        start = text.find(heading)
        if start == -1:
            continue
        rest = text[start + len(heading):]
        end = rest.find("\n## ")
        return rest if end == -1 else rest[:end]
    return ""


def _parse_citations(card_path: pathlib.Path, text: str) -> tuple[Citation, ...]:
    """อ่านลิงก์หน้าต้นฉบับจากการ์ด แล้วแปลงเป็นพาธจริงในคลัง"""
    found: list[Citation] = []
    seen: set[tuple[pathlib.Path, int | None]] = set()
    for label, target in _LINK.findall(_section(text, _CITATION_HEADINGS)):
        href, _, anchor = target.partition("#")
        if not href.endswith(".md"):
            continue
        resolved = (card_path.parent / href).resolve()
        if not resolved.is_relative_to(HARNESSES) or not resolved.exists():
            continue
        page_match = re.search(r"pdf-page-(\d+)", anchor)
        page = int(page_match.group(1)) if page_match else None
        key = (resolved, page)
        if key in seen:
            continue
        seen.add(key)
        found.append(Citation(label.strip(), resolved, page))
    return tuple(found)


def _requires(text: str) -> tuple[str, ...]:
    """คำบอกเกมย่อยที่การ์ดต้องการ เช่น การ์ด Hi/Lo ไม่ควรตอบคำถาม PLO high"""
    match = _REQUIRES.search(text)
    if not match:
        return ()
    return tuple(term.strip() for term in match.group(1).split(",") if term.strip())


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


@functools.lru_cache(maxsize=1)
def load_cards() -> tuple[Card, ...]:
    """การ์ดหัวข้อทุกใบของทุกภาษา"""
    cards: list[Card] = []
    for language in LANGUAGES:
        folder = HARNESSES / language / "topics"
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            cards.append(Card(
                language=language,
                slug=path.stem,
                title=_title(text, path.stem),
                body=text,
                citations=_parse_citations(path, text),
                requires=_requires(text),
            ))
    return tuple(cards)


def read_page(citation: Citation) -> str:
    """ข้อความของหน้า PDF ที่ citation ชี้ไป ถ้าไม่ระบุหน้าให้คืนทั้งไฟล์"""
    text = citation.path.read_text(encoding="utf-8")
    if citation.page is None:
        return text
    matches = list(_PAGE_HEADING.finditer(text))
    for index, match in enumerate(matches):
        if int(match.group(1)) != citation.page:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[match.start():end].strip()
    return ""
