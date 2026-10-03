"""Local dashboard for tamkwai.com visits and messages. Runs on this Mac only (127.0.0.1).

The website writes visits and chat messages to the analytics store (scripts/web/analytics.py);
this server reads the same store with the key in the repo's .env (DATABASE_URL, the Neon
connection string, or ANALYTICS_DB for a local SQLite file). Nothing here is deployed.

    make admin            -> http://127.0.0.1:8792
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "web"))

import analytics  # noqa: E402

PAGE = Path(__file__).resolve().parent / "admin.html"
ICON = ROOT / "public" / "static" / "tamkwai-icon.png"
KEYS = ("DATABASE_URL", "POSTGRES_URL", "ANALYTICS_DB")
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' "
       "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    """The store keys from .env (KEY=value lines), without touching anything else in it."""
    found = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            if key in KEYS and value.strip():
                found[key] = value.strip().strip('"').strip("'")
    return found


def make_handler(store) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 - quiet
            return

        def _send(self, status: int, body: bytes, kind: str) -> None:
            try:
                self.send_response(status)
                for name, value in (("Content-Type", kind), ("Content-Length", str(len(body))),
                                    ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                                    ("Content-Security-Policy", CSP), ("Referrer-Policy", "no-referrer")):
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the page reloaded or moved on before the answer was ready

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            one = lambda key, default="": (query.get(key) or [default])[0]  # noqa: E731
            # Only this machine: refuse anything that did not come to the loopback host.
            if (self.headers.get("Host") or "").split(":")[0] not in ("127.0.0.1", "localhost"):
                self._json(403, {"error": "local only"})
                return
            try:
                if url.path == "/":
                    self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                elif url.path == "/static/tamkwai-icon.png" and ICON.is_file():
                    self._send(200, ICON.read_bytes(), "image/png")
                elif url.path == "/api/summary":
                    days = max(1, min(365, int(one("days", "30"))))
                    self._json(200, analytics.summary(store, days))
                elif url.path == "/api/messages":
                    self._json(200, {"messages": analytics.messages(store, int(one("limit", "100")),
                                                                    one("q")[:100], one("kind")[:40])})
                else:
                    self._json(404, {"error": "not found"})
            except (BrokenPipeError, ConnectionResetError):
                return
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except Exception as error:  # noqa: BLE001 - show the reason on the page
                self._json(502, {"error": f"database: {error}"})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8792)
    args = parser.parse_args()
    env = {**dotenv(), **{k: v for k, v in os.environ.items() if k in KEYS}}
    store = analytics.store_from_env(env)
    if store is None:
        print("No DATABASE_URL (Neon) or ANALYTICS_DB in .env or the environment; nothing to show.", file=sys.stderr)
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store))
    print(f"tamkwai dashboard on http://127.0.0.1:{args.port} ({type(store).__name__})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
