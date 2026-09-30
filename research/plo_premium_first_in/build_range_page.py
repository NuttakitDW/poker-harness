"""Embed the exported range into the range viewer page.

Usage: python build_range_page.py --stack 40  ->  output/web/range<stack>.html
"""

from __future__ import annotations

from pathlib import Path

from study import from_args

HERE = Path(__file__).resolve().parent


def main() -> None:
    study = from_args(__doc__)
    data = (study.generated / "range_first_in.json").read_text().replace("</", "<\\/")
    page = (HERE / "range_template.html").read_text().replace("{{DATA}}", data)
    out = HERE / "output" / "web" / f"range{study.stack}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
