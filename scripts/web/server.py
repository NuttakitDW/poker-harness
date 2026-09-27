"""ตามควายเวอร์ชันเว็บ หน้าแชตถามชาร์ต push/fold พิมพ์ถามหรือแนบรูปโต๊ะ ได้รูปชาร์ตแบบเดียวกับบอท Discord

ใช้แค่ไลบรารีมาตรฐานของ Python ไม่ต้องลงอะไรเพิ่ม ความจำของแต่ละคนอยู่ที่เบราว์เซอร์ (state.py)
เซิร์ฟเวอร์จึงไม่ต้องจำอะไร รันบน Vercel ได้ (api/index.py เป็น WSGI app) ต้องมี DEEPSEEK_API_KEY ถึงจะใช้โหมด AI กับอ่านรูปได้

ใช้:
    make web                     แล้วเปิด http://127.0.0.1:8000
    .venv/bin/python scripts/web/server.py --port 8080

ตั้งใน environment:
    WEB_STATE_SECRET      กุญแจลงลายเซ็นความจำ ทุกเครื่องต้องใช้ค่าเดียวกัน ไม่ตั้งจะสุ่มใหม่ทุกครั้งที่เปิด
    WEB_CANONICAL_HOST    โดเมนหลัก โดเมนอื่นย้ายมาที่นี่ด้วย 301 เช่น xn--42c7axbfy7dd.com (ตามควาย.com)
    WEB_TRUST_PROXY=1     นับคนถามจากที่อยู่ที่ proxy ต่อท้าย X-Forwarded-For
    WEB_LOG=stdout        จดคำถามลง log แทนไฟล์ (ดิสก์ของ Vercel เขียนไม่ได้)

API (JSON ทั้งหมด ทุกคำตอบมี state ส่งกลับมากับคำขอถัดไป):
    POST /api/ask    {"question": "BTN shove 10bb", "state": "..."}   "fresh": true ลืม spot เดิมก่อนถาม
    POST /api/image  {"image": "<base64>", "mime": "image/png", "question": "hold AJo", "state": "..."}
    POST /api/new    ลืม spot เดิม
    POST /api/ai     {"on": false}
    GET  /api/help?lang=en  ตัวอย่างคำถาม
"""

from __future__ import annotations

import argparse
import base64
import binascii
import dataclasses
import email.message
import http
import http.server
import json
import os
import pathlib
import re
import secrets
import sys
import threading
import urllib.parse
from typing import Callable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import chat  # noqa: E402
import spot_chart  # noqa: E402
import state  # noqa: E402

# Vercel เสิร์ฟ public/ ที่รากโปรเจกต์ผ่าน CDN เซิร์ฟเวอร์ในเครื่องเสิร์ฟโฟลเดอร์เดียวกัน
PUBLIC = pathlib.Path(__file__).resolve().parents[2] / "public"
PAGE = PUBLIC / "index.html"
STATIC = PUBLIC / "static"
# ชื่อไฟล์ที่เปิดให้โหลดได้ ตัวพิมพ์เล็ก ตัวเลข ขีด นามสกุลตามนี้เท่านั้น ออกนอกโฟลเดอร์ไม่ได้
STATIC_NAME = re.compile(r"[a-z0-9-]+\.(png)")
STATIC_TYPES = {"png": "image/png"}
STATIC_CACHE = "public, max-age=86400"
MAX_BODY_BYTES = 14_000_000  # รูป 10 MB เป็น base64 แล้วโตขึ้นราวหนึ่งในสาม
WARM_UP_QUESTION = "BTN shove 10bb"
SLOW_DOWN = "ถามถี่ไปหน่อย พักสักนาทีแล้วถามใหม่นะ"
BUSY = "ตอนนี้คนถามเยอะมาก รอสักนาทีแล้วถามใหม่นะ"
HEALTH_PATH = "/healthz"
SITE_PER_MINUTE = 120  # เพดานของทั้งเว็บ กันค่า AI บานแม้มีคนปลอมที่อยู่มาหลบเพดานรายคน
BAD_IMAGE = "ไฟล์นี้ไม่ใช่รูปที่อ่านได้ ใช้ PNG, JPEG, WebP หรือ GIF ไม่เกิน 10 MB"
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data: blob:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class RequestError(Exception):
    """คำขอใช้ไม่ได้ ส่งสถานะกับข้อความกลับไปให้หน้าเว็บ"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclasses.dataclass(frozen=True)
class Config:
    """ทุกอย่างที่ Handler ใช้ Vercel สร้างเซิร์ฟเวอร์เอง จึงผูกไว้กับคลาส Handler แทนเซิร์ฟเวอร์"""

    tools: chat.Tools
    limit: chat.RateLimit
    site_limit: chat.RateLimit
    codec: state.Codec
    canonical_host: str | None = None
    trust_proxy: bool = False

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        secret = env.get("WEB_STATE_SECRET")
        if not secret:
            print("ไม่มี WEB_STATE_SECRET สุ่มกุญแจใหม่ ความจำจะหายเมื่อเปิดเครื่องใหม่", flush=True)
        return cls(tools=chat.Tools(), limit=chat.RateLimit(),
                   site_limit=chat.RateLimit(per_window=SITE_PER_MINUTE),
                   codec=state.Codec(secret.encode() if secret else secrets.token_bytes(32)),
                   canonical_host=(env.get("WEB_CANONICAL_HOST") or "").lower() or None,
                   trust_proxy=env.get("WEB_TRUST_PROXY") == "1")


def result_json(result: chat.Result) -> dict:
    chart = base64.b64encode(result.chart).decode() if result.chart else None
    return {"lines": list(result.lines), "kind": result.kind, "chart": chart}


def decode_image(body: dict) -> tuple[bytes, str]:
    mime = body.get("mime")
    if not isinstance(mime, str) or not chat.accepts_image(mime) or not isinstance(body.get("image"), str):
        raise RequestError(400, BAD_IMAGE)
    try:
        data = base64.b64decode(body["image"], validate=True)
    except (binascii.Error, ValueError):
        raise RequestError(400, BAD_IMAGE) from None
    if not data or len(data) > chat.MAX_IMAGE_BYTES:
        raise RequestError(400, BAD_IMAGE)
    return data, mime


@dataclasses.dataclass(frozen=True)
class Reply:
    status: int
    content_type: str
    body: bytes
    cache: str = "no-store"
    location: str | None = None


def _json(status: int, data: dict) -> Reply:
    return Reply(status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode())


class Exchange:
    """คำขอหนึ่งครั้ง ไม่ขึ้นกับว่ามาทาง http.server ในเครื่องหรือ WSGI บน Vercel

    headers คือ email.message.Message (ค้นชื่อแบบไม่สนตัวพิมพ์) read(n) อ่าน body ได้ n ไบต์
    """

    def __init__(self, config: Config, method: str, target: str, headers: email.message.Message,
                 read: Callable[[int], bytes], client_ip: str) -> None:
        self.config = config
        self.method = method
        self.url = urllib.parse.urlsplit(target)
        self.target = target
        self.headers = headers
        self.read = read
        self.client_ip = client_ip

    def reply(self) -> Reply:
        moved = self._moved()
        if moved is not None:
            return moved
        if self.method == "GET":
            return self._get()
        if self.method == "POST":
            return self._post()
        return _json(405, {"lines": ["method not allowed"]})

    # ---------- routes ----------

    def _get(self) -> Reply:
        path = self.url.path
        if path == HEALTH_PATH:
            return Reply(200, "text/plain; charset=utf-8", b"ok")
        if path == "/":
            return Reply(200, "text/html; charset=utf-8", PAGE.read_bytes())
        if path.startswith("/static/"):
            return self._static(path.removeprefix("/static/"))
        if path == "/api/help":
            lang = urllib.parse.parse_qs(self.url.query).get("lang", ["th"])[0]
            text = spot_chart.HELP_GUIDE.get(lang, spot_chart.HELP_GUIDE["th"])
            return _json(200, {"text": text, "contact": spot_chart.CONTACT})
        return _json(404, {"lines": ["not found"]})

    def _post(self) -> Reply:
        routes = {"/api/ask": self._ask, "/api/image": self._image,
                  "/api/new": self._new, "/api/ai": self._ai}
        route = routes.get(self.url.path)
        if route is None:
            return _json(404, {"lines": ["not found"]})
        try:
            body = self._body()
            session = self.config.codec.decode(body.get("state"))
            status, data, after = route(body, session)
        except RequestError as error:
            return _json(error.status, {"lines": [str(error)]})
        return _json(status, {**data, "ai": after.ai, "state": self.config.codec.encode(after)})

    def _ask(self, body: dict, session: chat.Session) -> tuple[int, dict, chat.Session]:
        question = body.get("question")
        if not isinstance(question, str) or chat.invalid_question(question):
            raise RequestError(400, chat.invalid_question(question) if isinstance(question, str) else chat.EMPTY)
        if body.get("fresh") is True:
            # ตัวอย่างบนหน้าเว็บเป็นคำถามจบในตัว ไม่ยืมรางวัล ICM หรือตำแหน่งจากคำถามก่อน
            session = chat.forget(session)
        self._spend()
        result, after = chat.ask(question.strip(), session, self.config.tools)
        return 200, result_json(result), after

    def _image(self, body: dict, session: chat.Session) -> tuple[int, dict, chat.Session]:
        data, mime = decode_image(body)
        extra = body.get("question")
        if extra is not None and (not isinstance(extra, str) or len(extra) > chat.MAX_QUESTION_CHARS):
            raise RequestError(400, chat.TOO_LONG)
        self._spend()
        result, after = chat.ask_image(data, mime, (extra or "").strip() or None, session, self.config.tools)
        return 200, result_json(result), after

    def _new(self, body: dict, session: chat.Session) -> tuple[int, dict, chat.Session]:
        return 200, {"lines": [chat.FORGOT]}, chat.forget(session)

    def _ai(self, body: dict, session: chat.Session) -> tuple[int, dict, chat.Session]:
        if not isinstance(body.get("on"), bool):
            raise RequestError(400, "on must be true or false")
        said, after = chat.toggle_ai(session, body["on"])
        return 200, {"lines": [said]}, after

    # ---------- plumbing ----------

    def _static(self, name: str) -> Reply:
        match = STATIC_NAME.fullmatch(name)
        path = STATIC / name
        if match is None or not path.is_file():
            return _json(404, {"lines": ["not found"]})
        return Reply(200, STATIC_TYPES[match.group(1)], path.read_bytes(), cache=STATIC_CACHE)

    def _spend(self) -> None:
        """นับหนึ่งครั้งเฉพาะคำขอที่ต้องใช้ solver หรือ AI"""
        if not self.config.limit.allow(self._visitor()):
            raise RequestError(429, SLOW_DOWN)
        if not self.config.site_limit.allow("site"):
            raise RequestError(429, BUSY)

    def _visitor(self) -> str:
        """ที่อยู่ของคนถาม หลัง proxy ใช้ตัวท้ายสุดของ X-Forwarded-For ที่ proxy ต่อเอง
        ตัวหน้า ๆ คนถามใส่มาเองได้ ถ้าเชื่อจะหลบเพดานรายคนได้"""
        forwarded = self.headers.get("X-Forwarded-For", "")
        if self.config.trust_proxy and forwarded.strip():
            return forwarded.split(",")[-1].strip()
        return self.client_ip

    def _moved(self) -> Reply | None:
        """ย้ายโดเมนอื่นไปโดเมนหลักด้วย 301 health check ไม่ย้าย"""
        canonical = self.config.canonical_host
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if not canonical or self.url.path == HEALTH_PATH or host == canonical:
            return None
        return Reply(301, "text/plain; charset=utf-8", b"", location=f"https://{canonical}{self.target}")

    def _body(self) -> dict:
        # รับแค่ JSON เว็บอื่นส่งฟอร์มมาหลอกให้เบราว์เซอร์ถามแทนไม่ได้ เพราะ JSON ต้องผ่าน CORS ก่อน
        if self.headers.get_content_type() != "application/json":
            raise RequestError(415, "send JSON")
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            raise RequestError(400, "bad Content-Length") from None
        if length > MAX_BODY_BYTES:
            raise RequestError(413, BAD_IMAGE)
        raw = self.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RequestError(400, "bad JSON") from None
        if not isinstance(body, dict):
            raise RequestError(400, "bad JSON")
        return body


def reply_headers(reply: Reply) -> list[tuple[str, str]]:
    headers = [("Content-Type", reply.content_type), ("Content-Length", str(len(reply.body))),
               ("Cache-Control", reply.cache), ("X-Content-Type-Options", "nosniff"),
               ("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", CSP)]
    return headers + ([("Location", reply.location)] if reply.location else [])


class Handler(http.server.BaseHTTPRequestHandler):
    """ทางเข้าของเซิร์ฟเวอร์ในเครื่อง (make web)"""

    server_version = "tamkwai"
    config: Config  # ผูกด้วย bind()

    def log_message(self, format: str, *args) -> None:  # noqa: A002 บันทึกคำถามมีอยู่แล้ว ไม่พิมพ์ทุก request
        return

    def do_GET(self) -> None:  # noqa: N802
        self._answer()

    def do_POST(self) -> None:  # noqa: N802
        self._answer()

    def _answer(self) -> None:
        reply = Exchange(self.config, self.command, self.path, self.headers,
                         self.rfile.read, self.client_address[0]).reply()
        if reply.status == 413:
            self.close_connection = True  # body ที่ใหญ่เกินยังไม่ได้อ่าน ต่อ connection เดิมไม่ได้
        self.send_response(reply.status)
        for name, value in reply_headers(reply):
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(reply.body)


def wsgi(config: Config) -> Callable:
    """ทางเข้าของ Vercel: WSGI app ที่ใช้ Exchange ตัวเดียวกับเซิร์ฟเวอร์ในเครื่อง"""

    def app(environ: dict, start_response: Callable) -> list[bytes]:
        headers = email.message.Message()
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                headers[key[5:].replace("_", "-").title()] = value
        for key, name in (("CONTENT_TYPE", "Content-Type"), ("CONTENT_LENGTH", "Content-Length")):
            if environ.get(key):
                headers[name] = environ[key]
        query = environ.get("QUERY_STRING", "")
        target = environ.get("PATH_INFO", "/") + (f"?{query}" if query else "")
        reply = Exchange(config, environ["REQUEST_METHOD"], target, headers,
                         environ["wsgi.input"].read, environ.get("REMOTE_ADDR", "")).reply()
        start_response(f"{reply.status} {http.HTTPStatus(reply.status).phrase}", reply_headers(reply))
        return [reply.body]

    return app


def bind(config: Config) -> type[Handler]:
    """Handler ที่ผูก config แล้ว Vercel เรียกคลาสนี้ตรง ๆ เซิร์ฟเวอร์ในเครื่องก็ใช้คลาสเดียวกัน"""
    return type("BoundHandler", (Handler,), {"config": config})


def make_server(host: str, port: int, tools: chat.Tools | None = None,
                limit: chat.RateLimit | None = None, site_limit: chat.RateLimit | None = None,
                canonical_host: str | None = None, trust_proxy: bool = False,
                secret: bytes | None = None) -> http.server.ThreadingHTTPServer:
    """เซิร์ฟเวอร์ที่ยังไม่เริ่ม test ส่งของปลอมเข้ามาแทน solver กับ AI ได้"""
    config = Config(tools=tools or chat.Tools(), limit=limit or chat.RateLimit(),
                    site_limit=site_limit or chat.RateLimit(per_window=SITE_PER_MINUTE),
                    codec=state.Codec(secret or secrets.token_bytes(32)),
                    canonical_host=canonical_host.lower() if canonical_host else None,
                    trust_proxy=trust_proxy)
    app = http.server.ThreadingHTTPServer((host, port), bind(config))
    app.daemon_threads = True
    return app


def warm_up() -> None:
    """โหลดตารางและแก้ชาร์ตหนึ่งครั้ง คนแรกที่ถามจะได้ไม่รอ"""
    spot_chart.reply(WARM_UP_QUESTION)
    print("อุ่นเครื่องเสร็จ", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    app = http.server.ThreadingHTTPServer((args.host, args.port), bind(Config.from_env()))
    app.daemon_threads = True
    threading.Thread(target=warm_up, daemon=True).start()
    print(f"ตามควายเว็บ เปิดที่ http://{args.host}:{app.server_port}  (Ctrl+C ปิด)", flush=True)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
