"""ทางเข้าของ Vercel: WSGI app (pyproject.toml ชี้มาที่ api.index:app) รับทุกคำขอที่ไม่ใช่ไฟล์ใน public/

หน้าเว็บกับโลโก้ Vercel เสิร์ฟเองจาก public/ ผ่าน CDN ไม่ผ่าน Python
เครื่อง Vercel ไม่มีฟอนต์ไทย จึงชี้ชาร์ตไปที่ฟอนต์ใน assets/fonts

/api/discord (คำสั่ง / ของบอท Discord) ต้องตอบภายใน 3 วินาทีแม้เครื่องเย็น
จึงโหลดเว็บกับ solver ตอนมีคำขอของเว็บครั้งแรก ไม่ใช่ตอนเปิดเครื่อง
"""

import functools
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("CHART_FONT", str(ROOT / "assets" / "fonts" / "IBMPlexSansThaiLooped-Regular.ttf"))
sys.path.insert(0, str(ROOT / "scripts" / "web"))
sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))

import slash  # noqa: E402

discord_app = slash.wsgi(slash.Endpoint.from_env())


@functools.cache
def web_app():
    import server
    from PIL import features

    # ไม่มี raqm สระกับวรรณยุกต์ไทยในรูปชาร์ตจะวางผิดที่ พิมพ์ไว้ให้เห็นใน log ตอนเครื่องเปิด
    print(f"tamkwai web cold start: raqm={features.check('raqm')}", flush=True)
    return server.wsgi(server.Config.from_env())


def app(environ: dict, start_response):
    if environ.get("PATH_INFO") == slash.PATH:
        return discord_app(environ, start_response)
    return web_app()(environ, start_response)
