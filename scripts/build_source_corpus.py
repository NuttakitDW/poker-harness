#!/usr/bin/env python3
"""Extract the local poker-book archive into page-cited Markdown source records."""

from __future__ import annotations

import argparse
import binascii
import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "Poker book-20260922T043840Z-1-001.zip"
SOURCE_ROOT = ROOT / "sources" / "pdf"
EN_ROOT = ROOT / "harnesses" / "EN" / "sources"
TH_ROOT = ROOT / "harnesses" / "TH" / "sources"
MANIFEST = ROOT / "harnesses" / "source-manifest.json"
BRIEF = ROOT / "tmp" / "source-briefs.json"
EN_QUALITY = EN_ROOT / "source-quality.md"
TH_QUALITY = TH_ROOT / "source-quality.md"
PAGES_PER_CHUNK = 8

TITLES = {
    "915850_เอกสาร 1 (3).pdf": ("thai-document-915850", "บันทึกภาษาไทย: short stack cash game และ mindset"),
    "Getting-The-Answer-Key.pdf": ("getting-the-answer-key", "Getting the Answer: Answer Key"),
    "Getting-The-Spreadsheets.pdf": ("getting-the-spreadsheets", "Getting the Answer: Spreadsheets"),
    "2p2NL6max.pdf": ("two-plus-two-nl-six-max", "2+2 NL 6-Max"),
    "Strategies for Beating Small Stakes Poker Tournaments..pdf": ("strategies-beating-small-stakes-tournaments", "Strategies for Beating Small Stakes Poker Tournaments"),
    "Cash Game Killer (Ultimate Poker eBook).pdf": ("cash-game-killer", "Cash Game Killer"),
    "Play Optimal Poker.pdf": ("play-optimal-poker", "Play Optimal Poker"),
    "Doyle Brunson_s Super System 1.pdf": ("super-system-1", "Doyle Brunson's Super System 1"),
    "Peak Poker Performance.pdf": ("peak-poker-performance", "Peak Poker Performance"),
    "Hole Card Confessions.pdf": ("hole-card-confessions", "Hole Card Confessions"),
    "Negreanu_Holdem_Wisdom.pdf": ("negreanu-holdem-wisdom", "Negreanu's Hold'em Wisdom"),
    "GTO Crash Course Strategy Guide - Red Chip Poker.pdf": ("gto-crash-course", "GTO Crash Course Strategy Guide"),
    "Aaron Brown - The Poker Face of Wall Street.pdf": ("poker-face-of-wall-street", "The Poker Face of Wall Street"),
    "9036_DN_Workbook.pdf": ("dn-workbook-9036", "DN Workbook 9036"),
    "crushing_the_microstakes.pdf": ("crushing-the-microstakes", "Crushing the Microstakes"),
    "Pot_Limit_Omaha_Jeff_Hwang.pdf": ("pot-limit-omaha-jeff-hwang", "Pot-Limit Omaha — Jeff Hwang"),
    "9049_the_micro_stakes_playbook.pdf": ("micro-stakes-playbook-9049", "The Micro Stakes Playbook"),
    "Doyle Brunson_s Super System 2 - A Course in Power Poker (Doyle Brunson).pdf": ("super-system-2", "Doyle Brunson's Super System 2"),
    "Gripsed MTT Strategy Guide.pdf": ("gripsed-mtt-strategy-guide", "Gripsed MTT Strategy Guide"),
    "The Theory of Poker (Seventh printing, Complete) (David Sklansky).pdf": ("the-theory-of-poker", "The Theory of Poker — David Sklansky"),
    "The_Mental_Game_of_Poker_ Jared_Tendler.pdf": ("mental-game-of-poker", "The Mental Game of Poker — Jared Tendler"),
    "Poker-Math-Preflop-Workbook.pdf": ("poker-math-preflop-workbook", "Poker Math Preflop Workbook"),
    "Winning Secrets of Online Poker.pdf": ("winning-secrets-online-poker", "Winning Secrets of Online Poker"),
    "Annie_Duke_Decide_to_Play_Great_Poker.pdf": ("decide-to-play-great-poker", "Decide to Play Great Poker — Annie Duke"),
    "grinders manual.pdf": ("grinders-manual", "The Grinder's Manual"),
}

VERIFIED_VISUAL_NOTES = {
    ("poker-math-preflop-workbook", 11): [
        "Visual check: the PDF uses suit glyphs that are missing or misread in extracted text. The following six hand matchups were read from the rendered PDF page; no equity answers are supplied:",
        "1. AhAs vs KdKh",
        "2. AdAc vs AhKs",
        "3. AdAs vs Td9d",
        "4. AsAh vs Ac5c",
        "5. AsAd vs Th4c",
        "6. AcAs vs QhJh",
    ],
}


def run(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_archive_member(name: str) -> Path:
    path = Path(name)
    if "\\" in name or path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "Poker book":
        raise ValueError(f"Unsafe archive path: {name!r}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Unexpected archive member: {name!r}")
    return SOURCE_ROOT.joinpath(*path.parts[1:])


def extract_archive(archive: Path) -> list[Path]:
    paths: list[Path] = []
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            if member.is_dir():
                continue
            target = safe_archive_member(member.filename)
            if not target.resolve().is_relative_to(SOURCE_ROOT.resolve()):
                raise ValueError(f"Archive path escapes source directory: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ValueError(f"Refusing archive symlink destination: {target}")
            if target.exists() and target.stat().st_size == member.file_size and crc32(target) == member.CRC:
                paths.append(target)
                continue
            if target.exists():
                raise ValueError(f"Existing file differs from archive CRC or size; refusing to overwrite: {target}")
            with source.open(member) as incoming, target.open("xb") as outgoing:
                for block in iter(lambda: incoming.read(1024 * 1024), b""):
                    outgoing.write(block)
            paths.append(target)
    return paths


def crc32(path: Path) -> int:
    value = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value = binascii.crc32(block, value)
    return value


def page_count(pdf: Path) -> int:
    info = run("pdfinfo", str(pdf))
    match = re.search(r"^Pages:\s*(\d+)", info, re.MULTILINE)
    if not match:
        raise ValueError(f"pdfinfo did not report pages for {pdf}")
    return int(match.group(1))


def extract_pages(pdf: Path, expected: int) -> list[str]:
    if pdf.name.startswith("The Theory of Poker ("):
        # This scan contains two printed pages on each landscape PDF page.
        # Its left text extends to about x=445; the right starts beyond x=450.
        left = run("pdftotext", "-layout", "-enc", "UTF-8", "-x", "0", "-y", "0", "-W", "450", "-H", "713", str(pdf), "-")
        right = run("pdftotext", "-layout", "-enc", "UTF-8", "-x", "450", "-y", "0", "-W", "371", "-H", "713", str(pdf), "-")
        lpages, rpages = split_pages(left, expected, pdf), split_pages(right, expected, pdf)
        return [f"[LEFT PRINTED PAGE]\n{l.strip()}\n\n[RIGHT PRINTED PAGE]\n{r.strip()}" for l, r in zip(lpages, rpages)]
    raw = run("pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-")
    return split_pages(raw, expected, pdf)


def split_pages(raw: str, expected: int, pdf: Path) -> list[str]:
    pages = raw.split("\f")
    if pages[-1] == "":
        pages.pop()
    if len(pages) != expected:
        raise ValueError(f"Page mismatch for {pdf}: pdfinfo={expected}, pdftotext={len(pages)}")
    return [page.strip("\n\r") for page in pages]


def embedded_urls(pdf: Path) -> dict[int, list[str]]:
    found: dict[int, list[str]] = {}
    for line in run("pdfinfo", "-url", str(pdf)).splitlines():
        match = re.match(r"^\s*(\d+)\s+\S+\s+(https?://\S+)", line)
        if match:
            found.setdefault(int(match.group(1)), []).append(match.group(2))
    return found


def image_pages(pdf: Path) -> tuple[dict[int, int], int]:
    counts: Counter[int] = Counter()
    for line in run("pdfimages", "-list", str(pdf)).splitlines()[2:]:
        columns = line.split()
        if columns and columns[0].isdigit():
            counts[int(columns[0])] += 1
    return dict(counts), sum(counts.values())


def ocr_page(pdf: Path, slug: str, number: int) -> tuple[int, str]:
    cache = ROOT / "tmp" / "ocr" / slug / f"page-{number:04d}.txt"
    if cache.exists():
        return number, cache.read_text(encoding="utf-8").strip()
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=cache.parent) as work:
        image = Path(work) / "page"
        subprocess.run(
            ["pdftoppm", "-f", str(number), "-l", str(number), "-r", "150", "-gray", "-png", "-singlefile", str(pdf), str(image)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        ocr_command = (
            ["tesseract", str(image.with_suffix(".png")), "stdout", "-l", "eng"]
            if shutil.which("tesseract")
            else [str(ROOT / "tmp" / "ocr" / "ocr_image"), str(image.with_suffix(".png"))]
        )
        result = subprocess.run(
            ocr_command,
            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    content = result.stdout.strip()
    cache.write_text(content + "\n", encoding="utf-8")
    return number, content


def pdf_url(pdf: Path) -> str:
    return "../../../../sources/pdf/" + quote(pdf.relative_to(SOURCE_ROOT).as_posix(), safe="/")


def write_generated(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and "Generated by scripts/build_source_corpus.py" not in path.read_text(encoding="utf-8"):
        raise ValueError(f"Refusing to overwrite non-generated file: {path}")
    path.write_text(body, encoding="utf-8")


def low_text_ocr_note(low: list[int], attempted: list[int], language: str) -> str:
    pages = ", ".join(map(str, low))
    attempted_pages = ", ".join(map(str, attempted))
    if language == "TH":
        note = f"หน้าที่มีข้อความดึงได้น้อยกว่า 100 ตัวอักษร: {pages} อาจเป็นหน้าปก หน้าว่าง หรือหน้าที่มีภาพมาก"
        return note + (f" ทดลอง OCR แล้วในหน้า: {attempted_pages}; ข้อความ OCR ยังไม่ได้ตรวจทาน" if attempted else " ยังไม่ได้ทำ OCR สำหรับเล่มนี้")
    note = f"Pages with fewer than 100 non-whitespace characters: {pages}. These may be covers, blank pages, or image-heavy pages."
    return note + (f" OCR was attempted on pages {attempted_pages}; its text is unverified." if attempted else " No OCR was attempted for this book.")


def text_fence(content: str) -> str:
    """Choose a Markdown fence longer than any backtick run in the source."""
    return "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", content)), default=0))


def write_book(slug: str, title: str, pdf: Path, digest: str, pages: list[str], aliases: list[str], use_ocr: bool) -> dict:
    book_dir = EN_ROOT / slug
    pdf_link = pdf_url(pdf)
    counts = [len(re.sub(r"\s+", "", page)) for page in pages]
    low = [index for index, count in enumerate(counts, 1) if count < 100]
    empty = [index for index, count in enumerate(counts, 1) if count == 0]
    urls = embedded_urls(pdf)
    images, image_count = image_pages(pdf)
    ocr: dict[int, str] = {}
    if use_ocr:
        selected = sorted(set(low) & set(images))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for number, content in pool.map(lambda n: ocr_page(pdf, slug, n), selected):
                ocr[number] = content
    chunks = []
    for start in range(1, len(pages) + 1, PAGES_PER_CHUNK):
        end = min(start + PAGES_PER_CHUNK - 1, len(pages))
        filename = f"pages-{start:04d}-{end:04d}.md"
        lines = [
            "<!-- Generated by scripts/build_source_corpus.py -->",
            f"# {title}: PDF pages {start}–{end}",
            "",
            f"Source: [{pdf.relative_to(SOURCE_ROOT).as_posix()}]({pdf_link}) · SHA-256 `{digest}`",
            "",
            "Page numbers below are 1-based PDF page numbers, including covers and front matter.",
            "",
        ]
        for number in range(start, end + 1):
            content = pages[number - 1]
            lines += [f"## PDF page {number}", "", f"[Open source PDF]({pdf_link}#page={number})", ""]
            if content.strip():
                fence = text_fence(content)
                lines += [f"{fence}text", content, fence, ""]
            else:
                lines += ["[No extractable PDF text on this page. Consult the source PDF and any OCR supplement below.]", ""]
            if number in urls:
                lines += ["Embedded PDF links:", "", *[f"- {url}" for url in urls[number]], ""]
            if number in images:
                lines += [f"[This PDF page contains {images[number]} embedded image object(s). Consult the source PDF for visual content.]", ""]
            if number in ocr:
                lines += ["### OCR supplement (unverified)", "", "OCR from a locally rendered image. It may misread card ranks, suits, numbers, charts, or reading order; confirm against the source PDF.", ""]
                if ocr[number]:
                    fence = text_fence(ocr[number])
                    lines += [f"{fence}text", ocr[number], fence, ""]
                else:
                    lines += ["[OCR produced no text.]", ""]
            note = VERIFIED_VISUAL_NOTES.get((slug, number))
            if note:
                lines += ["### Verified visual note", "", *note, ""]
        write_generated(book_dir / filename, "\n".join(lines))
        chunks.append({"start": start, "end": end, "path": f"EN/sources/{slug}/{filename}"})
    index_lines = [
        "<!-- Generated by scripts/build_source_corpus.py -->",
        f"# {title}", "",
        f"Original PDF: [{pdf.relative_to(SOURCE_ROOT).as_posix()}]({pdf_link})", "",
        f"PDF pages: {len(pages)} · SHA-256: `{digest}`", "",
        "This is a page-faithful text extraction for source lookup. Text may omit diagrams, images, and visual formatting. PDF page numbers include front matter; consult the PDF for figures and tables.", "",
    ]
    if aliases:
        index_lines += ["Duplicate archive paths (same SHA-256):", "", *[f"- `{alias}`" for alias in aliases], ""]
    if low:
        index_lines += [low_text_ocr_note(low, sorted(ocr), "EN"), ""]
    index_lines += ["## Page ranges", "", *[f"- [PDF pages {chunk['start']}–{chunk['end']}]({Path(chunk['path']).name})" for chunk in chunks], ""]
    write_generated(book_dir / "index.md", "\n".join(index_lines))
    th_link = f"../../../../sources/pdf/{quote(pdf.relative_to(SOURCE_ROOT).as_posix(), safe='/')}"
    th_lines = [
        "<!-- Generated by scripts/build_source_corpus.py -->",
        f"# {title}", "",
        f"[เปิดไฟล์ PDF ต้นฉบับ]({th_link}) · จำนวน {len(pages)} หน้า · SHA-256 `{digest}`", "",
        "ข้อความที่ดึงจาก PDF ยังคงเป็นภาษาต้นฉบับ ไม่ใช่คำแปลภาษาไทย ใช้เลขหน้า PDF จริงในการอ้างอิง รวมหน้าปกและคำนำ ภาพ แผนภาพ และตารางบางส่วนอาจไม่ปรากฏในข้อความ จึงควรตรวจ PDF ต้นฉบับประกอบ", "",
        "## ช่วงหน้า", "",
        *[f"- [หน้า PDF {chunk['start']}–{chunk['end']}](../../../EN/sources/{slug}/{Path(chunk['path']).name})" for chunk in chunks], "",
    ]
    if low:
        th_lines += [low_text_ocr_note(low, sorted(ocr), "TH"), ""]
    write_generated(TH_ROOT / slug / "index.md", "\n".join(th_lines))
    return {"id": slug, "title": title, "source_pdf": pdf.relative_to(ROOT).as_posix(), "sha256": digest, "pdf_pages": len(pages), "aliases": aliases, "empty_text_pages": empty, "low_text_pages": low, "embedded_image_pages": sorted(images), "embedded_image_count": image_count, "embedded_url_pages": sorted(urls), "ocr_attempted_pages": sorted(ocr), "ocr_nonempty_pages": sorted(number for number, content in ocr.items() if content), "extraction_note": "PDF spread split left then right" if slug == "the-theory-of-poker" else None, "chunks": chunks, "en_index": f"EN/sources/{slug}/index.md", "th_index": f"TH/sources/{slug}/index.md"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE, help="Input ZIP archive")
    parser.add_argument("--ocr", action="store_true", help="OCR low-text pages containing embedded images (Tesseract or macOS Vision)")
    args = parser.parse_args()
    if args.ocr and not shutil.which("tesseract"):
        if not shutil.which("swiftc"):
            raise OSError("OCR requires Tesseract or macOS swiftc/Vision")
        executable = ROOT / "tmp" / "ocr" / "ocr_image"
        executable.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / "scripts" / "ocr_image.swift"
        if not executable.exists() or executable.stat().st_mtime < source.stat().st_mtime:
            subprocess.run(["swiftc", str(source), "-o", str(executable)], check=True)
    files = extract_archive(args.archive)
    if len(files) != len(set(files)):
        raise ValueError("Archive repeats a file path")
    by_hash: dict[str, list[Path]] = {}
    for pdf in files:
        by_hash.setdefault(sha256(pdf), []).append(pdf)
    manifest = []
    briefs = []
    for digest, paths in by_hash.items():
        pdf = next((path for path in paths if path.parent == SOURCE_ROOT), paths[0])
        slug, title = TITLES.get(pdf.name, (re.sub(r"[^a-z0-9]+", "-", pdf.stem.lower()).strip("-"), pdf.stem))
        count = page_count(pdf)
        pages = extract_pages(pdf, count)
        aliases = [path.relative_to(ROOT).as_posix() for path in paths if path != pdf]
        record = write_book(slug, title, pdf, digest, pages, aliases, args.ocr)
        manifest.append(record)
        snippets = [line.strip() for page in pages[:15] for line in page.splitlines() if 8 <= len(line.strip()) <= 140]
        briefs.append({"id": slug, "title": title, "pages": count, "first_15_pages_lines": snippets[:140], "low_text_page_count": len(record["low_text_pages"])})
        print(f"{slug}: {count} pages, {len(record['low_text_pages'])} low-text", flush=True)
    en = ["<!-- Generated by scripts/build_source_corpus.py -->", "# Poker source books", "", "Full text is organized by 1-based PDF page number. Each book links to its original PDF. This is source material, not verified strategy advice.", "", "[Extraction quality and known limitations](source-quality.md)", ""]
    th = ["<!-- Generated by scripts/build_source_corpus.py -->", "# ดัชนีหนังสือโป๊กเกอร์ต้นฉบับ", "", "เลือกหนังสือเพื่อเปิดข้อความที่ดึงจาก PDF ตามเลขหน้า PDF จริง ข้อความต้นฉบับยังคงเป็นภาษาของหนังสือ ไม่ใช่คำแปลภาษาไทย", "", "[คุณภาพการดึงข้อความและข้อจำกัดที่ตรวจพบ](source-quality.md)", ""]
    for record in manifest:
        en.append(f"- [{record['title']}]({record['id']}/index.md) — {record['pdf_pages']} PDF pages")
        th.append(f"- [{record['title']}]({record['id']}/index.md) — {record['pdf_pages']} หน้า PDF")
    write_generated(EN_ROOT / "index.md", "\n".join(en) + "\n")
    write_generated(TH_ROOT / "index.md", "\n".join(th) + "\n")
    ocr_count = sum(len(record["ocr_attempted_pages"]) for record in manifest)
    en_quality = ["<!-- Generated by scripts/build_source_corpus.py -->", "# Source extraction quality", "", f"The original PDFs remain authoritative for diagrams, tables, page layout, and any unreadable text. Local OCR was attempted on {ocr_count} low-text pages with embedded images; OCR text is marked unverified. A page below 100 non-whitespace characters may be a cover, blank page, or substantive image page. Embedded-image counts do not detect vector drawings or all chart/table layouts.", "", "The Theory of Poker uses two printed pages per landscape PDF page. Its extraction is ordered left then right and labels each side; citations still use the single physical PDF page number.", "", "| Book | PDF pages | Low-text pages | Embedded-image pages | Image objects | PDF URL pages | OCR pages |", "|---|---:|---:|---:|---:|---:|---:|"]
    th_quality = ["<!-- Generated by scripts/build_source_corpus.py -->", "# คุณภาพการดึงข้อความจากหนังสือต้นฉบับ", "", f"ให้ยึด PDF ต้นฉบับสำหรับภาพ แผนภาพ ตาราง รูปแบบหน้า และข้อความที่อ่านไม่ชัด ได้ทดลอง OCR ในเครื่องกับหน้าที่มีข้อความน้อยและมีภาพฝัง {ocr_count} หน้า โดยทำเครื่องหมายว่าข้อความ OCR ยังไม่ได้ตรวจทาน หน้าที่มีตัวอักษรไม่ถึง 100 ตัวอาจเป็นหน้าปก หน้าว่าง หรือหน้าภาพที่มีเนื้อหาสำคัญ จำนวนภาพที่ตรวจพบไม่ครอบคลุมภาพเวกเตอร์และแผนภูมิทุกชนิด", "", "The Theory of Poker เป็นไฟล์ PDF แบบหน้าคู่ ข้อความจัดเรียงจากหน้าพิมพ์ซ้ายไปขวา โดยอ้างอิงเลขหน้า PDF จริงหนึ่งหน้า", "", "| หนังสือ | หน้า PDF | หน้าข้อความน้อย | หน้ามีภาพฝัง | จำนวนภาพ | หน้ามีลิงก์ | หน้า OCR |", "|---|---:|---:|---:|---:|---:|---:|"]
    for record in manifest:
        values = f"{record['pdf_pages']} | {len(record['low_text_pages'])} | {len(record['embedded_image_pages'])} | {record['embedded_image_count']} | {len(record['embedded_url_pages'])} | {len(record['ocr_attempted_pages'])}"
        en_quality.append(f"| [{record['title']}]({record['id']}/index.md) | {values} |")
        th_quality.append(f"| [{record['title']}]({record['id']}/index.md) | {values} |")
    en_quality += ["", "## Specific extraction limits", "", "- [Poker Math Preflop Workbook, PDF page 11](poker-math-preflop-workbook/pages-0009-0016.md#pdf-page-11): suit symbols disappear and some card ranks are misread (for example Q may appear as O). A six-matchup visual transcription is attached to that page. Exercise pages throughout this workbook require comparison with the PDF before using card notation or numeric results.", "- [The Grinder's Manual, PDF page 49](grinders-manual/pages-0049-0056.md#pdf-page-49): the table/chart is visual content; the text layer does not reliably encode its structure. Consult the original PDF.", "- [The Theory of Poker](the-theory-of-poker/index.md): two printed pages share each PDF page. The extracted text is split into left and right blocks, but printed-page numbers do not equal physical PDF page numbers.", "- [The Theory of Poker, PDF pages 33–34](the-theory-of-poker/pages-0033-0040.md#pdf-page-33): tables in the source PDF itself have overlapping or clipped numbers. Do not infer numerical values from the extraction or reconstruct them as verified.", ""]
    th_quality += ["", "## ข้อจำกัดที่ตรวจพบ", "", "- [Poker Math Preflop Workbook หน้า PDF 11](poker-math-preflop-workbook/index.md): สัญลักษณ์ดอกไพ่หาย และอักษรหน้าไพ่บางตัวอ่านผิด เช่น Q เป็น O มีการถอดคู่ไพ่ 6 ข้อจากภาพจริงไว้ในหน้าข้อความนั้นแล้ว สำหรับโจทย์หน้าอื่นในเล่มนี้ควรเทียบ PDF ต้นฉบับก่อนใช้ข้อมูลไพ่หรือตัวเลข", "- [The Grinder's Manual หน้า PDF 49](grinders-manual/index.md): ตารางหรือแผนภาพไม่ได้อยู่ในชั้นข้อความอย่างครบถ้วน ควรเปิด PDF ต้นฉบับ", "- [The Theory of Poker](the-theory-of-poker/index.md): PDF หนึ่งหน้าประกอบด้วยหน้าพิมพ์สองหน้า ข้อความจัดเป็นฝั่งซ้ายและขวา แต่เลขหน้าพิมพ์ต่างจากเลขหน้า PDF", "- [The Theory of Poker หน้า PDF 33–34](the-theory-of-poker/index.md): ตารางใน PDF ต้นฉบับเองมีตัวเลขทับซ้อนหรือถูกตัด ไม่ควรอนุมานค่าตัวเลขจากข้อความที่ดึงหรือถอดใหม่โดยอ้างว่าตรวจสอบแล้ว", ""]
    en_quality += ["- [Super System 2, PDF page 251](super-system-2/pages-0249-0256.md#pdf-page-251): card suits in a stud eight-or-better example appear as literal question marks in the original PDF and extraction; do not infer those suits.", "- [Pot-Limit Omaha — Jeff Hwang, PDF page 35](pot-limit-omaha-jeff-hwang/pages-0033-0040.md#pdf-page-35): the opening example's card images are displaced into the prose, its right edge is clipped, and the extracted text omits the hands and board. Do not reconstruct exact cards or outs as verified.", ""]
    th_quality += ["- [Super System 2 หน้า PDF 251](../../EN/sources/super-system-2/pages-0249-0256.md#pdf-page-251): ดอกไพ่ในตัวอย่าง Stud eight-or-better ปรากฏเป็นเครื่องหมายคำถามทั้งใน PDF ต้นฉบับและข้อความที่สกัด จึงไม่ควรเดาดอกไพ่", "- [Pot-Limit Omaha — Jeff Hwang หน้า PDF 35](../../EN/sources/pot-limit-omaha-jeff-hwang/pages-0033-0040.md#pdf-page-35): ภาพไพ่ในตัวอย่างต้นบทเลื่อนแทรกข้อความและขอบขวาถูกตัด ส่วนข้อความสกัดไม่แสดงไพ่ส่วนตัวและบอร์ด จึงไม่ควรถอดไพ่หรือเอาต์ที่แน่นอนแล้วอ้างว่าตรวจยืนยัน", ""]
    write_generated(EN_QUALITY, "\n".join(en_quality) + "\n")
    write_generated(TH_QUALITY, "\n".join(th_quality) + "\n")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"archive": args.archive.name, "archive_entries": len(files), "unique_sha256": len(manifest), "total_unique_pdf_pages": sum(item["pdf_pages"] for item in manifest), "books": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BRIEF.parent.mkdir(parents=True, exist_ok=True)
    BRIEF.write_text(json.dumps(briefs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Total: {len(files)} PDFs, {len(manifest)} unique, {sum(item['pdf_pages'] for item in manifest)} unique PDF pages", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, ValueError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
