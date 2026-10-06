"""First-party visit counting and message storage for tamkwai.com.

Pages send small events to POST /api/collect (static/beacon.js): one "view" per page load,
"time" events with the milliseconds the page was visible and one "act" per thing a visitor did on
a page (scrolled, a button, a link; ``name`` says which). A visitor with an "act" is a person; one
without is "idle", most of them bots that run scripts. Bots that say so in their user agent are
kept with device "bot", so every count can show all three apart. Chat questions are stored by
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
NAME = re.compile(r"[A-Za-z0-9#:/_.\-]{1,80}")
BOT = re.compile(r"bot|crawl|spider|slurp|preview|headless|lighthouse|monitor", re.I)
KINDS = ("view", "time", "act")

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS visits (
        ts DOUBLE PRECISION NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
        visitor TEXT NOT NULL, session TEXT NOT NULL, ms INTEGER NOT NULL, referrer TEXT NOT NULL,
        country TEXT NOT NULL, device TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS visits_day ON visits (day)",
    "ALTER TABLE visits ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''",
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
    if BOT.search(user_agent or ""):
        return "bot"
    return "phone" if re.search(r"Mobi|Android|iPhone", user_agent or "") else "desktop"


def parse_event(raw: bytes, *, user_agent: str, country: str, host: str, now: float) -> dict:
    """One beacon body -> a row for ``visits``. Raises EventError for anything not worth storing."""
    if len(raw) > MAX_EVENT_BYTES:
        raise EventError("too large")
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
    name = ""
    if body["kind"] == "act":
        name = body.get("name")
        if not (isinstance(name, str) and NAME.fullmatch(name)):
            raise EventError("bad name")
    country = (country or "").upper()
    return {"ts": now, "day": day_of(now), "kind": body["kind"], "path": path.removesuffix(".html") or "/",
            "visitor": visitor, "session": session, "ms": ms,
            "referrer": referrer_host(body.get("referrer"), host) if body["kind"] == "view" else "",
            "country": country if COUNTRY.fullmatch(country) else "", "device": device_of(user_agent), "name": name}


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
                    try:
                        connection.execute(statement.replace("DOUBLE PRECISION", "REAL")
                                           .replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN"))
                    except sqlite3.OperationalError as error:
                        if "duplicate column" not in str(error):
                            raise
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
    store.execute("INSERT INTO visits (ts, day, kind, path, visitor, session, ms, referrer, country, device, name) "
                  "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                  tuple(row[k] for k in ("ts", "day", "kind", "path", "visitor", "session", "ms", "referrer",
                                         "country", "device", "name")))


def save_message(store, row: dict) -> None:
    store.execute("INSERT INTO messages (ts, day, channel, source, question, kind, detail) "
                  "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                  tuple(row[k] for k in ("ts", "day", "channel", "source", "question", "kind", "detail")))


# ---------------------------------------------------------------- reports (local dashboard)

def _num(value) -> float:
    return float(value or 0)


# Who each visitor in the window is: "bot" (a page view said so), "human" (did something) or "idle" (neither).
WHO = ("WITH who AS (SELECT visitor, CASE WHEN MAX(CASE WHEN device = 'bot' AND kind = 'view' THEN 1 ELSE 0 END) = 1 THEN 'bot' "
       "WHEN MAX(CASE WHEN kind = 'act' THEN 1 ELSE 0 END) = 1 THEN 'human' ELSE 'idle' END AS who "
       "FROM visits WHERE day >= $1 GROUP BY visitor) ")
GROUPS = ("human", "idle", "bot")


def summary(store, days: int = 30, now: float | None = None) -> dict:
    """Everything the dashboard's overview shows, for the last ``days`` days (Bangkok time).

    Every visitor count is split by ``WHO``. The queries are independent, so they run at the same
    time (each is one HTTPS round trip on Neon). ``$2`` repeats ``$1`` for the SQLite placeholders.
    """
    now = time.time() if now is None else now
    since = day_of(now - (days - 1) * 86_400)
    joined = "FROM visits v JOIN who w ON w.visitor = v.visitor WHERE v.day >= $2 "
    top = (WHO + "SELECT v.{c} AS name, w.who, COUNT(DISTINCT v.visitor) AS visitors " + joined +
           "AND v.kind = 'view' GROUP BY v.{c}, w.who")
    stats = ("COUNT(DISTINCT v.visitor) AS visitors, SUM(CASE WHEN v.kind = 'view' THEN 1 ELSE 0 END) AS views, "
             "COUNT(DISTINCT v.session) AS sessions, SUM(v.ms) AS ms ")
    queries = {
        "daily": WHO + "SELECT v.day, w.who, " + stats + joined + "GROUP BY v.day, w.who",
        "totals": WHO + "SELECT w.who, " + stats + joined + "GROUP BY w.who",
        "pages": WHO + "SELECT v.path, w.who, " + stats + joined + "GROUP BY v.path, w.who",
        "actions": "SELECT path, name, COUNT(DISTINCT visitor) AS visitors, COUNT(*) AS n FROM visits "
                   "WHERE day >= $1 AND kind = 'act' AND device <> 'bot' GROUP BY path, name "
                   "ORDER BY visitors DESC, n DESC, name LIMIT 40",
        "asked": "SELECT day, COUNT(*) AS n FROM messages WHERE day >= $1 GROUP BY day",
        "kinds": "SELECT kind, COUNT(*) AS n FROM messages WHERE day >= $1 GROUP BY kind ORDER BY n DESC",
        "referrer": top.format(c="referrer"), "country": top.format(c="country"), "device": top.format(c="device"),
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = {name: pool.submit(store.execute, sql, (since, since) if "$2" in sql else (since,))
                   for name, sql in queries.items()}
        got = {name: future.result() for name, future in futures.items()}
    asked = {r["day"]: int(_num(r["n"])) for r in got["asked"]}
    by_who = {r["who"]: _stats(r) for r in got["totals"]}
    who = {g: by_who.get(g, _stats({})) for g in GROUPS}
    totals = {k: sum(who[g][k] for g in GROUPS) for k in ("visitors", "views", "sessions", "ms")}
    return {
        "since": since, "days": days,
        "totals": {"visitors": totals["visitors"], "views": totals["views"], "sessions": totals["sessions"],
                   "avg_session_seconds": totals["ms"] / 1000 / max(1, totals["sessions"]),
                   "messages": sum(asked.values())},
        "who": {g: {"visitors": w["visitors"], "views": w["views"], "sessions": w["sessions"],
                    "avg_session_seconds": w["ms"] / 1000 / max(1, w["sessions"])} for g, w in who.items()},
        "daily": [{"day": day, "visitors": sum(s["visitors"] for s in split.values()),
                   "humans": split.get("human", {}).get("visitors", 0), "bots": split.get("bot", {}).get("visitors", 0),
                   "views": sum(s["views"] for s in split.values()), "messages": asked.get(day, 0)}
                  for day, split in sorted(_pivot(got["daily"], "day").items())],
        "pages": sorted(({"path": path, "views": sum(s["views"] for s in split.values()),
                          "visitors": sum(s["visitors"] for s in split.values()),
                          "humans": split.get("human", {}).get("visitors", 0),
                          "avg_seconds": sum(s["ms"] for s in split.values()) / 1000
                          / max(1, sum(s["views"] for s in split.values()))}
                         for path, split in _pivot(got["pages"], "path").items()),
                        key=lambda p: (-p["views"], p["path"]))[:20],
        "actions": [{"path": r["path"], "name": r["name"], "visitors": int(_num(r["visitors"])), "count": int(_num(r["n"]))}
                    for r in got["actions"]],
        "referrers": _ranked(got["referrer"]), "countries": _ranked(got["country"]), "devices": _ranked(got["device"]),
        "message_kinds": [{"kind": r["kind"], "count": int(_num(r["n"]))} for r in got["kinds"]],
    }


def _stats(row: dict) -> dict:
    return {k: int(_num(row.get(k))) for k in ("visitors", "views", "sessions", "ms")}


def _pivot(rows: list[dict], key: str) -> dict:
    """Rows of (key, who, stats...) -> {key: {who: stats}}."""
    out: dict = {}
    for r in rows:
        out.setdefault(r[key], {})[r["who"]] = _stats(r)
    return out


def _ranked(rows: list[dict], limit: int = 12) -> list[dict]:
    """(name, who, visitors) rows -> the top names with all visitors and the people among them."""
    merged: dict = {}
    for r in rows:
        entry = merged.setdefault(r["name"] or "", {"name": r["name"] or "", "visitors": 0, "humans": 0})
        entry["visitors"] += int(_num(r["visitors"]))
        if r["who"] == "human":
            entry["humans"] += int(_num(r["visitors"]))
    return sorted(merged.values(), key=lambda e: (-e["visitors"], e["name"]))[:limit]


def messages(store, limit: int = 100, search: str = "", kind: str = "") -> list[dict]:
    limit = max(1, min(500, int(limit)))
    rows = store.execute(
        "SELECT ts, channel, source, question, kind, detail FROM messages "
        "WHERE ($1 = '' OR LOWER(question) LIKE $2 OR LOWER(detail) LIKE $3) AND ($4 = '' OR kind = $5) "
        "ORDER BY ts DESC LIMIT $6",
        (search, f"%{search.lower()}%", f"%{search.lower()}%", kind, kind, limit))
    return [{**r, "ts": _num(r["ts"]), "detail": json.loads(r["detail"] or "{}")} for r in rows]
