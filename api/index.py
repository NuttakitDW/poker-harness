"""ทางเข้าของ Vercel: WSGI app (pyproject.toml ชี้มาที่ api.index:app) รับทุกคำขอที่ไม่ใช่ไฟล์ใน public/

หน้าเว็บกับโลโก้ Vercel เสิร์ฟเองจาก public/ ผ่าน CDN ไม่ผ่าน Python
เครื่อง Vercel ไม่มีฟอนต์ไทย จึงชี้ชาร์ตไปที่ฟอนต์ใน assets/fonts
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("CHART_FONT", str(ROOT / "assets" / "fonts" / "IBMPlexSansThaiLooped-Regular.ttf"))
sys.path.insert(0, str(ROOT / "scripts" / "web"))

from PIL import features  # noqa: E402

import server  # noqa: E402

# ไม่มี raqm สระกับวรรณยุกต์ไทยในรูปชาร์ตจะวางผิดที่ พิมพ์ไว้ให้เห็นใน log ตอนเครื่องเปิด
print(f"tamkwai web cold start: raqm={features.check('raqm')}", flush=True)

app = server.wsgi(server.Config.from_env())
