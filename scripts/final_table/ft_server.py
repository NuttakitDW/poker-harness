"""Local final-table ICM solver: a page to describe the table (or read it from a screenshot),
solve it on every core of this machine, and explore the result.

Run ``make ft`` and open http://127.0.0.1:8790. Solves run one at a time as a separate
process (python -m plo_premium_proof ft-solve) so the page stays responsive; each keeps its
spec, status and result under tmp/final_table/jobs/<id>/ and can be reopened later.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import table_reader  # noqa: E402

from plo_premium_proof.finaltable import (  # noqa: E402
    RESULT,
    STATUS,
    STOP,
    FinalTableSpec,
    SpecError,
)

PAGE = Path(__file__).resolve().parent / "ft.html"
STATIC = ROOT / "public" / "static"
JOBS = ROOT / "tmp" / "final_table" / "jobs"
STATIC_NAME = re.compile(r"[a-z0-9-]+\.(png|json|js|css)")
STATIC_TYPES = {"png": "image/png", "json": "application/json", "js": "text/javascript; charset=utf-8",
                "css": "text/css; charset=utf-8"}
JOB_ID = re.compile(r"\d{8}-\d{6}")
MAX_BODY = 14_000_000
# The final table the page opens with: 7 seats, places 1-7 still to be paid.
DEFAULT_PAYOUTS = (1531.94, 1136.36, 842.99, 625.36, 463.91, 344.15, 255.30)


class Jobs:
    """Solve folders on disk plus the one process that may be running."""

    def __init__(self, folder: Path = JOBS, python: str = sys.executable) -> None:
        self.folder = folder
        self.python = python
        self.running: tuple[str, subprocess.Popen] | None = None

    def busy(self) -> str | None:
        if self.running and self.running[1].poll() is None:
            return self.running[0]
        return None

    def start(self, spec: FinalTableSpec) -> str:
        if self.busy():
            raise SpecError("a solve is already running: stop it first")
        job = time.strftime("%Y%m%d-%H%M%S")
        folder = self.folder / job
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "spec.json").write_text(json.dumps(spec.to_dict(), indent=1))
        log = (folder / "log.txt").open("w")
        process = subprocess.Popen(
            [self.python, "-m", "plo_premium_proof", "ft-solve", "--spec", str(folder / "spec.json"),
             "--output", str(folder)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        self.running = (job, process)
        return job

    def status(self, job: str) -> dict:
        folder = self.folder / job
        path = folder / STATUS
        status = json.loads(path.read_text()) if path.exists() else {"state": "starting"}
        alive = self.busy() == job
        if status.get("state") in ("starting", "building", "solving") and not alive:
            log = (folder / "log.txt").read_text()[-1500:] if (folder / "log.txt").exists() else ""
            status = {**status, "state": "failed", "log": log}
        return {**status, "id": job, "running": alive, "has_result": (folder / RESULT).exists()}

    def result(self, job: str) -> bytes | None:
        path = self.folder / job / RESULT
        return path.read_bytes() if path.exists() else None

    def stop(self, job: str) -> None:
        (self.folder / job / STOP).touch()

    def listing(self) -> list[dict]:
        if not self.folder.exists():
            return []
        out = []
        for folder in sorted(self.folder.iterdir(), reverse=True):
            if folder.is_dir() and JOB_ID.fullmatch(folder.name) and (folder / "spec.json").exists():
                spec = json.loads((folder / "spec.json").read_text())
                out.append({"id": folder.name, "spec": spec, "state": self.status(folder.name)["state"]})
        return out


def make_handler(jobs: Jobs) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 quiet: the page polls every second
            pass

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message})

        def do_GET(self) -> None:  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            if path in ("/", "/ft"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path.startswith("/static/"):
                name = path.removeprefix("/static/")
                match = STATIC_NAME.fullmatch(name)
                if match and (STATIC / name).is_file():
                    self._send(200, (STATIC / name).read_bytes(), STATIC_TYPES[match.group(1)])
                else:
                    self._error(404, "not found")
            elif path == "/api/info":
                self._json(200, {"cpus": os.cpu_count(), "payouts": DEFAULT_PAYOUTS, "running": jobs.busy(),
                                 "jobs": jobs.listing()})
            elif (match := re.fullmatch(r"/api/jobs/([\d-]+)/(status|result)", path)) and JOB_ID.fullmatch(match[1]):
                if not (jobs.folder / match[1]).is_dir():
                    self._error(404, "no such solve")
                elif match[2] == "status":
                    self._json(200, jobs.status(match[1]))
                elif (body := jobs.result(match[1])) is None:
                    self._error(404, "no result yet")
                else:
                    self._send(200, body, "application/json")
            else:
                self._error(404, "not found")

        def do_POST(self) -> None:  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            try:
                body = self._body()
                if path == "/api/detect":
                    self._json(200, table_reader.read(*self._image(body)))
                elif path == "/api/solve":
                    job = jobs.start(FinalTableSpec.from_dict(body.get("spec") or {}))
                    self._json(200, {"id": job})
                elif (match := re.fullmatch(r"/api/jobs/([\d-]+)/stop", path)) and JOB_ID.fullmatch(match[1]):
                    jobs.stop(match[1])
                    self._json(200, {"ok": True})
                else:
                    self._error(404, "not found")
            except (SpecError, table_reader.ReadError) as error:
                self._error(400, str(error))

        def _body(self) -> dict:
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_BODY:
                raise SpecError("request too large")
            try:
                data = json.loads(self.rfile.read(size) or b"{}")
            except json.JSONDecodeError as error:
                raise SpecError("request is not JSON") from error
            if not isinstance(data, dict):
                raise SpecError("request must be a JSON object")
            return data

        @staticmethod
        def _image(body: dict) -> tuple[bytes, str]:
            match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,(.+)", str(body.get("image") or ""), re.DOTALL)
            if not match:
                raise table_reader.ReadError("send a PNG, JPEG or WebP image")
            try:
                return base64.b64decode(match[2], validate=True), match[1]
            except binascii.Error as error:
                raise table_reader.ReadError("the image is not valid base64") from error

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Jobs()))
    print(f"final-table solver on http://127.0.0.1:{args.port} ({os.cpu_count()} cores)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
