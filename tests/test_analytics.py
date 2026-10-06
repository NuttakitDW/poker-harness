from __future__ import annotations

import http.client
import io
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "web"))
sys.path.insert(0, str(ROOT / "scripts" / "admin"))

import admin_server  # noqa: E402
import analytics  # noqa: E402
import chat  # noqa: E402
import server  # noqa: E402

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"
NOW = 1_790_990_000.0  # 2026-10-03 in Bangkok


def event(**fields) -> bytes:
    return json.dumps({"kind": "view", "path": "/plo", "visitor": "a1b2c3d4e5f60718",
                       "session": "0011223344556677", **fields}).encode()


class ParseEventTest(unittest.TestCase):
    def parse(self, raw, ua=UA, country="th"):
        return analytics.parse_event(raw, user_agent=ua, country=country, host="tamkwai.com", now=NOW)

    def test_view_keeps_only_anonymous_fields(self):
        row = self.parse(event(referrer="https://www.google.com/search?q=plo"))
        self.assertEqual((row["kind"], row["path"], row["referrer"], row["country"], row["device"], row["ms"]),
                         ("view", "/plo", "google.com", "TH", "phone", 0))
        self.assertEqual(row["day"], analytics.day_of(NOW))
        self.assertNotIn("ip", row)
        self.assertEqual(self.parse(event(referrer="https://tamkwai.com/research"))["referrer"], "")

    def test_time_needs_sane_milliseconds(self):
        self.assertEqual(self.parse(event(kind="time", ms=45_000))["ms"], 45_000)
        for bad in (0, -5, analytics.MAX_TIME_MS + 1, "100", True):
            with self.subTest(ms=bad), self.assertRaises(analytics.EventError):
                self.parse(event(kind="time", ms=bad))

    def test_rejects_junk_and_oversize(self):
        for raw in (b"nope", b"[]", event(kind="click"), event(path="https://evil"), event(path="/<script>"),
                    event(visitor="X" * 8), event(session="short"), b"{" + b" " * 3000 + b"}"):
            with self.subTest(raw=raw[:40]), self.assertRaises(analytics.EventError):
                self.parse(raw)

    def test_declared_bots_are_kept_and_marked(self):
        self.assertEqual(self.parse(event(), ua="Googlebot/2.1")["device"], "bot")

    def test_act_needs_a_short_plain_name(self):
        row = self.parse(event(kind="act", name="matrix:card"))
        self.assertEqual((row["kind"], row["name"], row["ms"], row["referrer"]), ("act", "matrix:card", 0, ""))
        self.assertEqual(self.parse(event(kind="act", name="link:/static/a.pdf"))["name"], "link:/static/a.pdf")
        self.assertEqual(self.parse(event())["name"], "")
        for bad in (None, "", "x" * 81, "<b>", "a b", 5):
            with self.subTest(name=bad), self.assertRaises(analytics.EventError):
                self.parse(event(kind="act", name=bad))


class SqliteReportTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = analytics.SqliteStore(str(pathlib.Path(self.folder.name) / "a.db"))

    def tearDown(self):
        self.folder.cleanup()

    def add(self, kind="view", path="/", visitor="aaaaaaaa", session="ssssssss", ms=0, now=NOW, referrer="",
            name="", ua="Mozilla/5.0 (Macintosh)"):
        row = analytics.parse_event(json.dumps({"kind": kind, "path": path, "visitor": visitor, "session": session,
                                                "ms": ms, "referrer": referrer, "name": name}).encode(),
                                    user_agent=ua, country="TH", host="tamkwai.com", now=now)
        analytics.save_visit(self.store, row)

    def test_summary_counts_visitors_views_and_time(self):
        self.add(path="/", visitor="aaaaaaaa", session="s1111111", referrer="https://discord.com/x")
        self.add(path="/plo", visitor="aaaaaaaa", session="s1111111")
        self.add(kind="time", path="/plo", visitor="aaaaaaaa", session="s1111111", ms=90_000)
        self.add(path="/", visitor="bbbbbbbb", session="s2222222")
        self.add(kind="time", path="/", visitor="bbbbbbbb", session="s2222222", ms=30_000)
        self.add(path="/", visitor="cccccccc", session="s3333333", now=NOW - 40 * 86_400)  # outside 30 days
        analytics.save_message(self.store, analytics.message_row({"question": "BTN shove 10bb", "source": "text",
                                                                  "kind": "chart"}, channel="web", now=NOW))
        s = analytics.summary(self.store, 30, now=NOW)
        self.assertEqual((s["totals"]["visitors"], s["totals"]["views"], s["totals"]["sessions"]), (2, 3, 2))
        self.assertAlmostEqual(s["totals"]["avg_session_seconds"], 60.0)
        self.assertEqual(s["totals"]["messages"], 1)
        self.assertEqual(s["daily"][0]["visitors"], 2)
        self.assertEqual(s["referrers"][0], {"name": "", "visitors": 2, "humans": 0})
        self.assertIn({"name": "discord.com", "visitors": 1, "humans": 0}, s["referrers"])
        plo = next(p for p in s["pages"] if p["path"] == "/plo")
        self.assertEqual((plo["views"], plo["avg_seconds"]), (1, 90.0))

    def test_visitors_split_into_humans_idle_and_bots(self):
        self.add(path="/o8", visitor="aaaaaaaa", session="s1111111")
        self.add(kind="act", path="/o8", visitor="aaaaaaaa", session="s1111111", name="scroll")
        self.add(kind="act", path="/o8", visitor="aaaaaaaa", session="s1111111", name="matrix:card")
        self.add(kind="time", path="/o8", visitor="aaaaaaaa", session="s1111111", ms=120_000)
        self.add(path="/", visitor="bbbbbbbb", session="s2222222")                      # opened, did nothing
        self.add(kind="time", path="/", visitor="bbbbbbbb", session="s2222222", ms=2_000)
        self.add(path="/", visitor="cccccccc", session="s3333333", ua="Googlebot/2.1")   # says it is a bot
        self.add(kind="act", path="/", visitor="dddddddd", session="s4444444", name="#send", now=NOW - 40 * 86_400)
        self.add(path="/", visitor="dddddddd", session="s5555555")                      # acted, but not this window
        s = analytics.summary(self.store, 30, now=NOW)
        who = s["who"]
        self.assertEqual((who["human"]["visitors"], who["idle"]["visitors"], who["bot"]["visitors"]), (1, 2, 1))
        self.assertAlmostEqual(who["human"]["avg_session_seconds"], 120.0)
        self.assertEqual(s["totals"]["visitors"], 4)                                     # bots still counted
        self.assertEqual(s["daily"][0]["humans"], 1)
        self.assertEqual(s["daily"][0]["bots"], 1)
        o8 = next(p for p in s["pages"] if p["path"] == "/o8")
        self.assertEqual((o8["views"], o8["humans"]), (1, 1))
        self.assertEqual(s["actions"][0], {"path": "/o8", "name": "matrix:card", "visitors": 1, "count": 1})
        self.assertEqual({a["name"] for a in s["actions"]}, {"matrix:card", "scroll"})
        self.assertIn({"name": "bot", "visitors": 1, "humans": 0}, s["devices"])

    def test_message_search_and_kind_filter(self):
        for i, (q, kind) in enumerate((("BTN shove 10bb", "chart"), ("what is ICM", "ai"), ("hold AJo vs BTN", "chart"))):
            analytics.save_message(self.store, analytics.message_row({"question": q, "source": "text", "kind": kind,
                                                                      "parsed": None}, channel="web", now=NOW + i))
        self.assertEqual(len(analytics.messages(self.store)), 3)
        self.assertEqual([m["question"] for m in analytics.messages(self.store, search="btn")],
                         ["hold AJo vs BTN", "BTN shove 10bb"])
        self.assertEqual([m["question"] for m in analytics.messages(self.store, kind="ai")], ["what is ICM"])


class NeonStoreTest(unittest.TestCase):
    def test_posts_sql_to_the_https_endpoint(self):
        store = analytics.NeonStore("postgresql://user:pw@ep-cool-1.ap-southeast-1.aws.neon.tech/db?sslmode=require")
        sent = []

        def fake_open(request, timeout):
            sent.append((request.full_url, dict(request.header_items()), json.loads(request.data)))
            return io.BytesIO(json.dumps({"rows": [{"n": "3"}]}).encode())

        with mock.patch("urllib.request.urlopen", fake_open):
            rows = store.execute("SELECT COUNT(*) AS n FROM visits WHERE day >= $1", ("2026-10-01",))
        self.assertEqual(rows, [{"n": "3"}])
        url, headers, body = sent[-1]
        self.assertEqual(url, "https://ep-cool-1.ap-southeast-1.aws.neon.tech/sql")
        self.assertIn("Neon-connection-string", headers)
        self.assertEqual(body, {"query": "SELECT COUNT(*) AS n FROM visits WHERE day >= $1", "params": ["2026-10-01"]})
        self.assertEqual(len(sent), len(analytics.SCHEMA) + 1)  # schema once, then the query
        with self.assertRaises(ValueError):
            analytics.NeonStore("https://not-a-db")


class CollectRouteTest(unittest.TestCase):
    def run_server(self, store):
        app = server.make_server("127.0.0.1", 0, analytics_store=store)
        threading.Thread(target=app.serve_forever, daemon=True).start()
        self.addCleanup(app.server_close)
        self.addCleanup(app.shutdown)
        return app.server_port

    def post(self, port, body, content_type="text/plain", ua=UA):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("POST", "/api/collect", body, {"Content-Type": content_type, "User-Agent": ua})
        response = connection.getresponse()
        response.read()
        connection.close()
        return response.status

    def test_events_are_stored_and_always_answer_204(self):
        with tempfile.TemporaryDirectory() as folder:
            store = analytics.SqliteStore(str(pathlib.Path(folder) / "a.db"))
            port = self.run_server(store)
            self.assertEqual(self.post(port, event()), 204)
            self.assertEqual(self.post(port, event(kind="time", ms=5000)), 204)
            self.assertEqual(self.post(port, b"garbage"), 204)
            self.assertEqual(self.post(port, event(kind="act", name="#send")), 204)
            self.assertEqual(self.post(port, event(), ua="bingbot"), 204)
            rows = store.execute("SELECT kind, ms, name, device FROM visits ORDER BY ts")
            self.assertEqual([(r["kind"], r["ms"], r["name"], r["device"]) for r in rows],
                             [("view", 0, "", "phone"), ("time", 5000, "", "phone"), ("act", 0, "#send", "phone"),
                              ("view", 0, "", "bot")])

    def test_an_old_sqlite_file_gets_the_name_column(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(pathlib.Path(folder) / "old.db")
            import sqlite3
            with sqlite3.connect(path) as old:
                old.execute(analytics.SCHEMA[0].replace("DOUBLE PRECISION", "REAL"))
            store = analytics.SqliteStore(path)
            analytics.save_visit(store, analytics.parse_event(event(kind="act", name="scroll"), user_agent=UA,
                                                              country="", host="tamkwai.com", now=NOW))
            self.assertEqual(store.execute("SELECT name FROM visits")[0]["name"], "scroll")

    def test_without_a_store_nothing_happens(self):
        self.assertEqual(self.post(self.run_server(None), event()), 204)

    def test_public_pages_load_the_beacon(self):
        for page in sorted(p.stem for p in (ROOT / "public").glob("*.html")):
            with self.subTest(page=page):
                self.assertIn('<script src="/static/beacon.js" defer></script>',
                              (ROOT / "public" / f"{page}.html").read_text())


class MessageRecordTest(unittest.TestCase):
    def test_chat_questions_are_stored_when_a_store_is_set(self):
        with tempfile.TemporaryDirectory() as folder:
            store = analytics.SqliteStore(str(pathlib.Path(folder) / "a.db"))
            with mock.patch.object(chat, "_message_store", lambda: store), \
                    mock.patch.dict("os.environ", {"WEB_LOG": "stdout"}), mock.patch("builtins.print"):
                chat._record({"question": "CO open 25bb", "source": "text", "kind": "chart", "request": None,
                              "server": "web", "channel": None})
            rows = analytics.messages(store)
            self.assertEqual((rows[0]["question"], rows[0]["kind"], rows[0]["channel"]), ("CO open 25bb", "chart", "web"))

    def test_the_reply_the_visitor_saw_is_stored_and_searchable(self):
        with tempfile.TemporaryDirectory() as folder:
            store = analytics.SqliteStore(str(pathlib.Path(folder) / "a.db"))
            talk = lambda text, solve, history, memory: type("A", (), {  # noqa: E731 - AI that only talks
                "say": "Hi! Tell me your seat and stack.", "query": None, "made": None, "history": ()})()
            tools = chat.Tools(answer=talk)
            with mock.patch.object(chat, "_message_store", lambda: store), mock.patch("builtins.print"), \
                    mock.patch.object(chat.question_log, "record", lambda *a, **k: None):
                chat.ask("hello there", chat.Session(), tools)
                chat.ask("K8 vs A7 equity", chat.Session(ai=False), tools)
            rows = analytics.messages(store)
            self.assertEqual(rows[1]["detail"]["reply"], "Hi! Tell me your seat and stack.")
            self.assertIn("A7  60.3%", rows[0]["detail"]["reply"])
            self.assertEqual([m["question"] for m in analytics.messages(store, search="seat and stack")],
                             ["hello there"])


class AdminServerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        store = analytics.SqliteStore(str(pathlib.Path(self.folder.name) / "a.db"))
        app = ThreadingHTTPServer(("127.0.0.1", 0), admin_server.make_handler(store))
        threading.Thread(target=app.serve_forever, daemon=True).start()
        self.addCleanup(app.server_close)
        self.addCleanup(app.shutdown)
        self.port = app.server_port

    def get(self, path, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", path, headers={"Host": host or f"127.0.0.1:{self.port}"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_page_and_reports(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Copyright", body)
        self.assertNotIn(b"innerHTML", body)          # messages are rendered as text only
        status, body = self.get("/api/summary?days=7")
        self.assertEqual((status, json.loads(body)["totals"]["visitors"]), (200, 0))
        self.assertEqual(self.get("/api/messages?q=btn")[0], 200)

    def test_other_hosts_are_refused(self):
        self.assertEqual(self.get("/api/summary", host="evil.example")[0], 403)

    def test_dotenv_reads_only_store_keys(self):
        path = pathlib.Path(self.folder.name) / ".env"
        path.write_text('DEEPSEEK_API_KEY=secret\nexport DATABASE_URL="postgresql://u:p@h/db"\n')
        self.assertEqual(admin_server.dotenv(path), {"DATABASE_URL": "postgresql://u:p@h/db"})


if __name__ == "__main__":
    unittest.main()
