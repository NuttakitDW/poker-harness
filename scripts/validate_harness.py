#!/usr/bin/env python3
"""Validate the generated poker source corpus against its archive and links."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "harnesses" / "source-manifest.json"
ARCHIVE = ROOT / "Poker book-20260922T043840Z-1-001.zip"
LINK = re.compile(r"(?<!!)\[[^\]]*\]\((<[^>]+>|(?:[^()]|\([^()]*\))*)\)")
PAGE = re.compile(r"^## PDF page (\d+)$", re.MULTILINE)
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
NO_PDF_TEXT = "[No extractable PDF text on this page."
TOPIC_HEADINGS = {
    "EN": {"Core idea", "Worked example (authored; not quoted from source)", "Source pages"},
    "TH": {"แนวคิดหลัก", "ตัวอย่างที่เรียบเรียงใหม่ (ไม่ได้คัดจากต้นฉบับ)", "หน้าต้นฉบับ"},
}
GUIDE_HEADINGS = {
    "EN": {"Reading route", "Original chapter route", "Explained study themes", "Scope and verification"},
    "TH": {"เส้นทางอ่าน", "เส้นทางบทต้นฉบับ", "คำอธิบายแก่นเรื่อง", "ขอบเขตและการตรวจสอบ"},
}


def prose_only(body: str) -> str:
    lines = []
    marker: str | None = None
    for line in body.splitlines():
        match = FENCE.match(line)
        if marker is not None:
            if match and match.group(1)[0] == marker[0] and len(match.group(1)) >= len(marker) and not match.group(2).strip():
                marker = None
            lines.append("")
        elif match and (match.group(1)[0] == "~" or "`" not in match.group(2)):
            marker = match.group(1)
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines)


def headings(body: str) -> set[str]:
    result = set()
    for line in prose_only(body).splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if match:
            value = re.sub(r"[^\w\-\s]", "", match.group(1).lower(), flags=re.UNICODE)
            result.add(re.sub(r"\s+", "-", value.strip()))
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def crc32(path: Path) -> int:
    value = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value = binascii.crc32(block, value)
    return value


def source_page_sections(body: str) -> dict[int, str]:
    """Split on headings outside fenced extraction, retaining the page bodies."""
    raw_lines = body.splitlines()
    visible_lines = prose_only(body).splitlines()
    starts = [(int(match.group(1)), index) for index, line in enumerate(visible_lines)
              if (match := PAGE.fullmatch(line))]
    return {number: "\n".join(raw_lines[start + 1:starts[pos + 1][1] if pos + 1 < len(starts) else len(raw_lines)])
            for pos, (number, start) in enumerate(starts)}


def native_text_present(page_body: str) -> bool:
    """Require a closed, nonempty native PDF text block before OCR content."""
    marker: str | None = None
    native = False
    content: list[str] = []
    for line in page_body.splitlines():
        if marker is None and line == "### OCR supplement (unverified)":
            break
        match = FENCE.match(line)
        if marker is not None:
            if match and match.group(1)[0] == marker[0] and len(match.group(1)) >= len(marker) and not match.group(2).strip():
                if native and "".join(content).strip():
                    return True
                marker = None
                native = False
                content = []
            elif native:
                content.append(line)
        elif match and (match.group(1)[0] == "~" or "`" not in match.group(2)):
            marker = match.group(1)
            native = match.group(2).strip() == "text"
    return False


def validate_curated(root: Path, books: list[dict]) -> list[str]:
    errors = []
    book_ids = {book["id"] for book in books}
    for language in ("EN", "TH"):
        base = root / "harnesses" / language
        for subdir, expected, required in (
            ("guides", book_ids, GUIDE_HEADINGS[language]),
            ("topics", None, TOPIC_HEADINGS[language]),
        ):
            files = {path.stem: path for path in (base / subdir).glob("*.md") if path.name != "index.md"}
            if expected is not None and set(files) != expected:
                errors.append(f"{language} guide coverage differs from manifest: missing={sorted(expected - set(files))} extra={sorted(set(files) - expected)}")
            if subdir == "topics" and len(files) != 21:
                errors.append(f"{language} topic count differs from expected 21: {len(files)}")
            index = base / ("guides/index.md" if subdir == "guides" else "INDEX.md")
            if not index.is_file():
                errors.append(f"Missing {language} {subdir} index: {index}")
            else:
                indexed = {Path(urlsplit(link).path).stem for link in LINK.findall(prose_only(index.read_text(encoding="utf-8")))
                           if urlsplit(link).path.startswith(subdir + "/") or (subdir == "guides" and urlsplit(link).path.endswith(".md") and "/" not in urlsplit(link).path)}
                if indexed != set(files):
                    errors.append(f"{language} {subdir} index coverage differs: missing={sorted(set(files) - indexed)} extra={sorted(indexed - set(files))}")
            for slug, path in files.items():
                body = prose_only(path.read_text(encoding="utf-8"))
                found = set(re.findall(r"^## (.+)$", body, re.MULTILINE))
                if missing := required - found:
                    errors.append(f"Missing sections {sorted(missing)}: {path}")
                if subdir == "topics":
                    if not re.search(rf"`{re.escape(slug)}`", body):
                        errors.append(f"Missing stable topic ID {slug}: {path}")
                    section = body.split("## Source pages\n", 1)[-1].split("## หน้าต้นฉบับ\n", 1)[-1].split("\n## ", 1)[0]
                    if not re.search(r"sources/[^/)]+/pages-\d+-\d+\.md#pdf-page-\d+", section):
                        errors.append(f"Missing page-specific source citation: {path}")
                elif not re.search(rf"sources/{re.escape(slug)}/index\.md", body):
                    errors.append(f"Missing matching source catalog link: {path}")
                if subdir == "guides" and not re.search(r"\.pdf#page=\d+", body):
                    errors.append(f"Missing page-specific PDF citation: {path}")
    return errors


def validate() -> list[str]:
    errors: list[str] = []
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    books = data["books"]
    if len(books) != data["unique_sha256"] or sum(book["pdf_pages"] for book in books) != data["total_unique_pdf_pages"]:
        errors.append("Manifest aggregate counts disagree with books")
    with zipfile.ZipFile(ARCHIVE) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != data["archive_entries"]:
            errors.append("Archive entry count differs from manifest")
        bad_member = archive.testzip()
        if bad_member:
            errors.append(f"Archive CRC failure: {bad_member}")
        archive_names = {m.filename for m in members}
        archive_crc = {m.filename: m.CRC for m in members}
    all_sources: set[str] = set()
    pdf_pages: dict[Path, int] = {}
    for book in books:
        pdf = ROOT / book["source_pdf"]
        if not pdf.is_file() or sha256(pdf) != book["sha256"]:
            errors.append(f"Missing or changed source PDF: {pdf}")
        pdf_pages[pdf.resolve()] = book["pdf_pages"]
        archive_name = "Poker book/" + pdf.relative_to(ROOT / "sources" / "pdf").as_posix()
        if archive_name not in archive_names:
            errors.append(f"Source PDF absent from archive: {pdf}")
        elif pdf.is_file() and crc32(pdf) != archive_crc[archive_name]:
            errors.append(f"Source PDF CRC differs from archive: {pdf}")
        all_sources.add(archive_name)
        for alias in book["aliases"]:
            target = ROOT / alias
            if not target.is_file() or sha256(target) != book["sha256"]:
                errors.append(f"Missing or non-identical alias: {alias}")
            alias_name = "Poker book/" + target.relative_to(ROOT / "sources" / "pdf").as_posix()
            if alias_name in archive_crc and target.is_file() and crc32(target) != archive_crc[alias_name]:
                errors.append(f"Alias CRC differs from archive: {target}")
            all_sources.add(alias_name)
            pdf_pages[target.resolve()] = book["pdf_pages"]
        expected = list(range(1, book["pdf_pages"] + 1))
        actual: list[int] = []
        for chunk in book["chunks"]:
            file = ROOT / "harnesses" / chunk["path"]
            if not file.is_file():
                errors.append(f"Missing chunk: {file}")
                continue
            body = file.read_text(encoding="utf-8")
            seen = list(map(int, PAGE.findall(prose_only(body))))
            if seen != list(range(chunk["start"], chunk["end"] + 1)):
                errors.append(f"Page headings differ from range: {file}")
            actual.extend(seen)
            sections = source_page_sections(body)
            for number in seen:
                page_body = sections.get(number, "")
                if f"#page={number})" not in page_body:
                    errors.append(f"Missing PDF page citation {number}: {file}")
                if number in book["empty_text_pages"]:
                    if NO_PDF_TEXT not in page_body:
                        errors.append(f"Empty PDF text page lacks explicit notice {number}: {file}")
                elif not native_text_present(page_body):
                    errors.append(f"Extracted source text absent on page {number}: {file}")
                if number in book["ocr_attempted_pages"] and "### OCR supplement (unverified)" not in page_body:
                    errors.append(f"OCR supplement absent on page {number}: {file}")
        if actual != expected:
            errors.append(f"Missing, extra, or reordered source page: {book['id']}")
        for key in ("en_index", "th_index"):
            if not (ROOT / "harnesses" / book[key]).is_file():
                errors.append(f"Missing book index: {book[key]}")
        for key in ("empty_text_pages", "low_text_pages", "embedded_image_pages", "embedded_url_pages"):
            if any(not 1 <= value <= book["pdf_pages"] for value in book[key]):
                errors.append(f"Out-of-bounds {key}: {book['id']}")
    if all_sources != archive_names:
        errors.append(f"Archive coverage differs: missing={sorted(archive_names - all_sources)} extra={sorted(all_sources - archive_names)}")
    for subdir in ("topics", "guides"):
        en = {path.name for path in (ROOT / "harnesses" / "EN" / subdir).glob("*.md")}
        th = {path.name for path in (ROOT / "harnesses" / "TH" / subdir).glob("*.md")}
        if en != th:
            errors.append(f"EN/TH {subdir} file parity differs: EN-only={sorted(en-th)}, TH-only={sorted(th-en)}")
    errors.extend(validate_curated(ROOT, books))
    markdown_files = [ROOT / "README.md", ROOT / "AGENTS.md", *(ROOT / "harnesses").rglob("*.md")]
    for file in markdown_files:
        if not file.is_file():
            continue
        body = prose_only(file.read_text(encoding="utf-8"))
        for target in LINK.findall(body):
            target = target.strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            parsed = urlsplit(target)
            if parsed.scheme:
                continue
            linked = (file.parent / unquote(parsed.path)).resolve() if parsed.path else file.resolve()
            if not linked.exists():
                errors.append(f"Broken link {target} in {file}")
                continue
            if parsed.fragment.startswith("page=") and linked.suffix.lower() == ".pdf":
                try:
                    page = int(parsed.fragment[5:])
                except ValueError:
                    errors.append(f"Invalid PDF page fragment {target} in {file}")
                else:
                    if not 1 <= page <= pdf_pages.get(linked, 0):
                        errors.append(f"Out-of-bounds PDF page fragment {target} in {file}")
            elif parsed.fragment and linked.suffix.lower() == ".md" and parsed.fragment not in headings(linked.read_text(encoding="utf-8")):
                errors.append(f"Missing Markdown heading fragment {target} in {file}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Validated archive coverage, source hashes and aliases, page bodies and citations, bilingual topic and guide coverage, and local Markdown links.")


if __name__ == "__main__":
    main()
