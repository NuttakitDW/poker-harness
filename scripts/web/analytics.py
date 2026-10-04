"""First-party visit counting and message storage for tamkwai.com.

Pages send small events to POST /api/collect (static/beacon.js): one "view" per page load and
"time" events with the milliseconds the page was visible. Chat questions are stored by
chat._record. Nothing identifies a person: no IP address, no user agent; a visitor is a random id
the browser keeps, a session is one tab.

The store is Postgres on Neon in production, reached over Neon's HTTPS SQL endpoint so the
Vercel bundle needs no database driver (DATABASE_URL). Without it, a SQLite file (ANALYTICS_DB)
serves local runs and tests. The website only writes; reading is for the local dashboard.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

BANGKOK = datetime.timezone(datetime.timedelta(hours=7))
MAX_EVENT_BYTES = 2_000
MAX_TIME_MS = 6 * 60 * 60 * 1000          # one report can't claim more than six hours
MAX_QUESTION_CHARS = 2_000
ID = re.compile(r"[a-z0-9]{8,32}")
PATH = re.compile(r"/[A-Za-z0-9/_.\-]{0,120}")
COUNTRY = re.compile(r"[A-Z]{2}")
BOT = re.compile(r"bot|crawl|spider|slurp|preview|headless|lighthouse|monitor", re.I)
KINDS = ("view", "time")

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS visits (
        ts DOUBLE PRECISION NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
        visitor TEXT NOT NULL, session TEXT NOT NULL, ms INTEGER NOT NULL, referrer TEXT NOT NULL,
        country TEXT NOT NULL, device TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS visits_day ON visits (day)",
    """CREATE TABLE IF NOT EXISTS messages (
        ts DOUBLE PRECISION NOT NULL, day TEXT NOT NULL, channel TEXT NOT NULL, source TEXT NOT NULL,
        question TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS messages_day ON messages (day)",
)


class EventError(ValueError):
    """An event that is not stored."""


# ---------------------------------------------------------------- validation

def day_of(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, BANGKOK).strftime("%Y-%m-%d")


def referrer_host(value: Any, own_host: str) -> str:
    """Where the visitor came from, host only; '' for direct visits and our own pages."""
    if not isinstance(value, str) or not value:
        return ""
    host = (urllib.parse.urlsplit(value[:300]).hostname or "").lower().removeprefix("www.")
    return "" if not host or host == own_host.removeprefix("www.") else host[:80]


def device_of(user_agent: str) -> str:
    return "phone" if re.search(r"Mobi|Android|iPhone", user_agent or "") else "desktop"


def parse_event(raw: bytes, *, user_agent: str, country: str, host: str, now: float) -> dict:
    """One beacon body -> a row for ``visits``. Raises EventError for anything not worth storing."""
    if len(raw) > MAX_EVENT_BYTES:
        raise EventError("too large")
    if BOT.search(user_agent or ""):
        raise EventError("bot")
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise EventError("bad json") from None
    if not isinstance(body, dict) or body.get("kind") not in KINDS:
        raise EventError("bad kind")
    path, visitor, session = body.get("path"), body.get("visitor"), body.get("session")
    if not (isinstance(path, str) and PATH.fullmatch(path)):
        raise EventError("bad path")
    if not all(isinstance(x, str) and ID.fullmatch(x) for x in (visitor, session)):
        raise EventError("bad id")
    ms = 0
    if body["kind"] == "time":
        ms = body.get("ms")
        if not isinstance(ms, int) or isinstance(ms, bool) or not 0 < ms <= MAX_TIME_MS:
            raise EventError("bad ms")
    country = (country or "").upper()
    return {"ts": now, "day": day_of(now), "kind": body["kind"], "path": path.removesuffix(".html") or "/",
            "visitor": visitor, "session": session, "ms": ms,
            "referrer": referrer_host(body.get("referrer"), host) if body["kind"] == "view" else "",
            "country": country if COUNTRY.fullmatch(country) else "", "device": device_of(user_agent)}


def message_row(entry: dict, *, channel: str, now: float) -> dict:
    """A logged chat question (question_log.entry) -> a row for ``messages``."""
    question = str(entry.get("question") or "")[:MAX_QUESTION_CHARS]
    detail = {k: v for k, v in entry.items() if k not in ("question", "source", "kind")}
    return {"ts": now, "day": day_of(now), "channel": channel, "source": str(entry.get("source") or ""),
            "question": question, "kind": str(entry.get("kind") or ""),
            "detail": json.dumps(detail, ensure_ascii=False, default=str)[:4_000]}


# ---------------------------------------------------------------- stores

class SqliteStore:
    """Local file store (development, tests)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        sql = re.sub(r"\$\d+", "?", sql)
        with self._lock, self._connect() as connection:
            if not self._ready:
                for statement in SCHEMA:
                    connection.execute(statement.replace("DOUBLE PRECISION", "REAL"))
                self._ready = True
            return [dict(row) for row in connection.execute(sql, params).fetchall()]


class NeonStore:
    """Postgres on Neon over its HTTPS SQL endpoint (no driver needed on Vercel)."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("postgres", "postgresql") or not parts.hostname:
            raise ValueError("DATABASE_URL must be a postgres:// connection string")
        self.url = url
        self.endpoint = f"https://{parts.hostname}/sql"
        self.timeout = timeout
        self._ready = False

    def _query(self, sql: str, params: tuple) -> list[dict]:
        request = urllib.request.Request(
            self.endpoint, data=json.dumps({"query": sql, "params": list(params)}).encode(),
            headers={"Content-Type": "application/json", "Neon-Connection-String": self.url}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - fixed https host
            return json.loads(response.read()).get("rows", [])

    def execute(self, sql: str, params: tuple = ()) -> list[dict]:
        if not self._ready:
            for statement in SCHEMA:
                self._query(statement, ())
            self._ready = True
        return self._query(sql, params)


def store_from_env(env=os.environ):
    """Neon when DATABASE_URL is set, else SQLite when ANALYTICS_DB is set, else None (off)."""
    url = env.get("DATABASE_URL") or env.get("POSTGRES_URL")
    if url:
        return NeonStore(url)
    if env.get("ANALYTICS_DB"):
        return SqliteStore(env["ANALYTICS_DB"])
    return None


def save_visit(store, row: dict) -> None:
    store.execute("INSERT INTO visits (ts, day, kind, path, visitor, session, ms, referrer, country, device) "
                  "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
                  tuple(row[k] for k in ("ts", "day", "kind", "path", "visitor", "session", "ms", "referrer",
                                         "country", "device")))


def save_message(store, row: dict) -> None:
    store.execute("INSERT INTO messages (ts, day, channel, source, question, kind, detail) "
                  "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                  tuple(row[k] for k in ("ts", "day", "channel", "source", "question", "kind", "detail")))


# ---------------------------------------------------------------- reports (local dashboard)

def _num(value) -> float:
    return float(value or 0)


def summary(store, days: int = 30, now: float | None = None) -> dict:
    """Everything the dashboard's overview shows, for the last ``days`` days (Bangkok time).

    The queries are independent, so they run at the same time (each is one HTTPS round trip on Neon).
    """
    now = time.time() if now is None else now
    since = day_of(now - (days - 1) * 86_400)
    top = ("SELECT {c} AS name, COUNT(DISTINCT visitor) AS visitors FROM visits "
           "WHERE day >= $1 AND kind = 'view' GROUP BY {c} ORDER BY visitors DESC LIMIT 12")
    queries = {
        "daily": "SELECT day, COUNT(DISTINCT visitor) AS visitors, SUM(CASE WHEN kind = 'view' THEN 1 ELSE 0 END) "
                 "AS views, COUNT(DISTINCT session) AS sessions, SUM(ms) AS ms FROM visits WHERE day >= $1 "
                 "GROUP BY day ORDER BY day",
        "asked": "SELECT day, COUNT(*) AS n FROM messages WHERE day >= $1 GROUP BY day",
        "pages": "SELECT path, SUM(CASE WHEN kind = 'view' THEN 1 ELSE 0 END) AS views, COUNT(DISTINCT visitor) "
                 "AS visitors, SUM(ms) AS ms FROM visits WHERE day >= $1 GROUP BY path ORDER BY views DESC LIMIT 20",
        "totals": "SELECT COUNT(DISTINCT visitor) AS visitors, COUNT(DISTINCT session) AS sessions, SUM(ms) AS ms, "
                  "SUM(CASE WHEN kind = 'view' THEN 1 ELSE 0 END) AS views FROM visits WHERE day >= $1",
        "kinds": "SELECT kind, COUNT(*) AS n FROM messages WHERE day >= $1 GROUP BY kind ORDER BY n DESC",
        "referrer": top.format(c="referrer"), "country": top.format(c="country"), "device": top.format(c="device"),
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = {name: pool.submit(store.execute, sql, (since,)) for name, sql in queries.items()}
        got = {name: future.result() for name, future in futures.items()}
    asked = {r["day"]: int(_num(r["n"])) for r in got["asked"]}
    totals = got["totals"][0]
    sessions = max(1, int(_num(totals["sessions"])))
    named = lambda rows: [{"name": r["name"] or "", "visitors": int(_num(r["visitors"]))} for r in rows]  # noqa: E731
    return {
        "since": since, "days": days,
        "totals": {"visitors": int(_num(totals["visitors"])), "views": int(_num(totals["views"])),
                   "sessions": int(_num(totals["sessions"])), "avg_session_seconds": _num(totals["ms"]) / 1000 / sessions,
                   "messages": sum(asked.values())},
        "daily": [{"day": r["day"], "visitors": int(_num(r["visitors"])), "views": int(_num(r["views"])),
                   "avg_session_seconds": _num(r["ms"]) / 1000 / max(1, int(_num(r["sessions"]))),
                   "messages": asked.get(r["day"], 0)} for r in got["daily"]],
        "pages": [{"path": r["path"], "views": int(_num(r["views"])), "visitors": int(_num(r["visitors"])),
                   "avg_seconds": _num(r["ms"]) / 1000 / max(1, int(_num(r["views"])))} for r in got["pages"]],
        "referrers": named(got["referrer"]), "countries": named(got["country"]), "devices": named(got["device"]),
        "message_kinds": [{"kind": r["kind"], "count": int(_num(r["n"]))} for r in got["kinds"]],
    }


def messages(store, limit: int = 100, search: str = "", kind: str = "") -> list[dict]:
    limit = max(1, min(500, int(limit)))
    rows = store.execute(
        "SELECT ts, channel, source, question, kind, detail FROM messages "
        "WHERE ($1 = '' OR LOWER(question) LIKE $2 OR LOWER(detail) LIKE $3) AND ($4 = '' OR kind = $5) "
        "ORDER BY ts DESC LIMIT $6",
        (search, f"%{search.lower()}%", f"%{search.lower()}%", kind, kind, limit))
    return [{**r, "ts": _num(r["ts"]), "detail": json.loads(r["detail"] or "{}")} for r in rows]
