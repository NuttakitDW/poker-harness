"""Checks the website version of the bot: the chat logic and the HTTP routes."""

import base64
import http.client
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "web"))
import chat  # noqa: E402
import server  # noqa: E402
import state  # noqa: E402
import assistant  # noqa: E402
import preflop  # noqa: E402
import plo_type  # noqa: E402

PNG = b"\x89PNG-chart"
MARIO = b"\x89PNG-mario"
REQUEST = preflop.Request(game="mtt", stack=8, hero="BB", villain="BTN", shovers=("BTN",),
                          payouts=(50.0, 30.0, 20.0))
SECRET = b"test-secret"


def found(request=REQUEST):
    return SimpleNamespace(book={"b": 1}, chart={"c": 1}, hands=("AKo",), lang="TH", request=request)


def made(kind="chart", message=None, spot=None):
    return SimpleNamespace(kind=kind, message=message, note="note",
                           found=spot if spot is not None else found())


class Recorder:
    """Stand-ins for the solver, the AI, the renderer and the log, remembering every call."""

    def __init__(self, reply=None, answer=None, question="aof BB vs CO shove 10bb", key="k"):
        self.calls, self.logged = [], []
        self.reply = reply or made()
        self.answer_value = answer
        self.question = question
        self.key = key

    def tools(self):
        return chat.Tools(solve=self.solve, answer=self.answer, render=self.render,
                          mario=lambda: MARIO, read_question=self.read_question,
                          vision_key=lambda: self.key, log=self.logged.append)

    def solve(self, question, memory=None, lang=None):
        self.calls.append(("solve", question, memory))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def answer(self, question, solve, history, memory):
        self.calls.append(("answer", question, history, memory))
        return self.answer_value

    def render(self, book, chart, hands, lang, notes):
        self.calls.append(("render", hands, lang, notes))
        return PNG

    def read_question(self, data, mime, key):
        self.calls.append(("read", data, mime, key))
        if isinstance(self.question, Exception):
            raise self.question
        return self.question


class AskTests(unittest.TestCase):
    def test_basic_mode_goes_straight_to_the_solver_with_the_remembered_spot(self):
        fake = Recorder()
        result, session = chat.ask("BTN shove 10bb", chat.Session(memory="OLD", ai=False), fake.tools())
        self.assertEqual(fake.calls[0], ("solve", "BTN shove 10bb", "OLD"))
        self.assertEqual(result.kind, "chart")
        self.assertEqual(result.chart, PNG)
        self.assertEqual(session.memory, REQUEST)

    def test_ai_mode_shows_what_the_model_said_and_the_query_it_wrote(self):
        answer = SimpleNamespace(say="ok", query="BTN shove 10bb", made=made(), history=("turn",))
        fake = Recorder(answer=answer)
        result, session = chat.ask("btn jam ten", chat.Session(), fake.tools())
        self.assertEqual(result.lines, ("ok", "query: BTN shove 10bb"))
        self.assertEqual(session.history, ("turn",))

    def test_the_query_line_is_hidden_when_the_model_kept_the_question(self):
        answer = SimpleNamespace(say="ok", query="BTN shove 10bb", made=made(), history=())
        result, _ = chat.ask("BTN shove 10bb", chat.Session(), Recorder(answer=answer).tools())
        self.assertEqual(result.lines, ("ok",))

    def test_small_talk_has_no_chart(self):
        answer = SimpleNamespace(say="hello", query=None, made=None, history=("t",))
        result, session = chat.ask("hi", chat.Session(memory="OLD"), Recorder(answer=answer).tools())
        self.assertEqual((result.kind, result.chart, result.lines), ("talk", None, ("hello",)))
        self.assertEqual(session.memory, "OLD")

    def test_a_message_instead_of_a_chart_is_shown_as_text(self):
        fake = Recorder(reply=made(kind="not_found", message="no chart", spot=None))
        fake.reply.found = None
        result, _ = chat.ask("??", chat.Session(ai=False), fake.tools())
        self.assertEqual(result.lines, ("no chart",))
        self.assertIsNone(result.chart)

    def test_actual_plo_question_returns_structured_sections_and_a_legacy_fallback(self):
        tools = chat.Tools(log=lambda _line: None)
        result, _ = chat.ask("plo A234 ss A2", chat.Session(ai=False), tools)
        self.assertEqual((result.kind, result.chart), ("plo_type", None))
        self.assertEqual(result.lines, (result.plo_fallback,))
        self.assertIn("Tier", result.plo_fallback)
        self.assertEqual([card["rank"] for card in result.plo["cards"]], list("A432"))
        self.assertIn("A2 share a suit", result.plo["title"])
        self.assertEqual(result.plo["tier"], "Trash")
        self.assertIn("Usually fold", result.plo["play"])
        self.assertIn("Suited Ace Hands", result.plo["type"])
        self.assertIn("nut flush", result.plo["miracle"])

    def test_no_structure_type_is_preserved_in_the_web_payload(self):
        payload = plo_type.presentation(plo_type.read("plo QJ76 rainbow"), "EN")
        self.assertEqual(payload["type"], "Everything else / no shared structure")

    def test_ai_mode_cannot_refuse_a_recognized_plo_hand(self):
        refusal = lambda *_args: assistant.Crafted("I only handle push/fold", None)
        tools = chat.Tools(log=lambda _line: None)
        with mock.patch.object(assistant, "craft", refusal), \
                mock.patch.object(assistant, "api_key", return_value="k"):
            for question, tier in (("plo AAKK ds", "Premium"), ("plo T885", "Trash")):
                with self.subTest(question=question):
                    result, _ = chat.ask(question, chat.Session(), tools)
                    self.assertEqual(result.kind, "plo_type")
                    self.assertTrue(result.plo["tier"].startswith(tier))
                    self.assertNotIn("only handle push/fold", " ".join(result.lines))

    def test_the_easter_egg_draws_mario(self):
        result, _ = chat.ask("mario", chat.Session(ai=False), Recorder(reply=made(kind="mario")).tools())
        self.assertEqual(result.chart, MARIO)

    def test_a_solver_crash_is_an_apology_and_keeps_the_session(self):
        fake = Recorder(reply=RuntimeError("boom"))
        before = chat.Session(memory="OLD", ai=False)
        result, session = chat.ask("BTN shove 10bb", before, fake.tools())
        self.assertEqual((result.kind, result.lines), ("error", (chat.FAILED,)))
        self.assertEqual(session, before)

    def test_every_question_is_logged_without_who_asked(self):
        fake = Recorder()
        chat.ask("BTN shove 10bb", chat.Session(ai=False), fake.tools())
        line = fake.logged[0]
        self.assertEqual((line["question"], line["kind"], line["server"]), ("BTN shove 10bb", "chart", "web"))
        self.assertNotIn("author", line)


class QuestionTests(unittest.TestCase):
    def test_blank_and_long_questions_are_refused(self):
        self.assertIsNotNone(chat.invalid_question("   "))
        self.assertIsNotNone(chat.invalid_question("x" * (chat.MAX_QUESTION_CHARS + 1)))
        self.assertIsNone(chat.invalid_question("BTN shove 10bb"))


class ImageTests(unittest.TestCase):
    def test_without_a_vision_key_the_site_asks_for_text(self):
        fake = Recorder(key=None)
        result, _ = chat.ask_image(b"img", "image/png", None, chat.Session(), fake.tools())
        self.assertEqual(result.lines, (chat.NO_VISION,))

    def test_an_unreadable_screenshot_says_so(self):
        fake = Recorder(question=ValueError("no table"))
        result, _ = chat.ask_image(b"img", "image/png", None, chat.Session(), fake.tools())
        self.assertEqual((result.kind, result.lines), ("not_read", (chat.NOT_READ,)))

    def test_a_screenshot_is_a_new_spot_asked_in_basic_mode(self):
        fake = Recorder()
        result, _ = chat.ask_image(b"img", "image/png", "hold AJo",
                                   chat.Session(memory="OLD"), fake.tools())
        self.assertEqual(fake.calls[1], ("solve", "aof BB vs CO shove 10bb hold AJo", None))
        self.assertEqual(result.lines[0], "อ่านจากรูปได้ว่า: aof BB vs CO shove 10bb hold AJo")
        self.assertEqual(result.chart, PNG)

    def test_only_common_image_types_are_accepted(self):
        self.assertTrue(chat.accepts_image("image/jpeg"))
        self.assertFalse(chat.accepts_image("image/svg+xml"))


class SessionTests(unittest.TestCase):
    def test_new_spot_forgets_the_spot_and_the_chat(self):
        self.assertEqual(chat.forget(chat.Session(memory="m", history=("h",), ai=False)),
                         chat.Session(ai=False))

    def test_turning_ai_off_also_drops_the_chat(self):
        _, session = chat.toggle_ai(chat.Session(history=("h",)), False)
        self.assertEqual(session, chat.Session(ai=False))



class StateTests(unittest.TestCase):
    """The browser keeps each visitor's memory, signed, so any serverless instance can answer."""

    def setUp(self):
        self.now = 1_000_000.0
        self.codec = state.Codec(SECRET, clock=lambda: self.now)
        self.session = chat.Session(memory=REQUEST, ai=False,
                                    history=(assistant.Turn("บีบีเจอบีทีเอ็น", '{"say": "ok"}'),))

    def test_a_session_survives_the_round_trip(self):
        self.assertEqual(self.codec.decode(self.codec.encode(self.session)), self.session)

    def test_no_token_is_a_fresh_session(self):
        for token in (None, "", "garbage", "a.b", 42):
            with self.subTest(token=token):
                self.assertEqual(self.codec.decode(token), chat.Session())

    def test_an_edited_token_is_ignored(self):
        body, signature = self.codec.encode(self.session).split(".")
        forged = state.Codec(b"other", clock=lambda: self.now).encode(chat.Session(ai=True)).split(".")[0]
        self.assertEqual(self.codec.decode(f"{forged}.{signature}"), chat.Session())

    def test_a_token_signed_with_another_secret_is_ignored(self):
        other = state.Codec(b"other", clock=lambda: self.now)
        self.assertEqual(self.codec.decode(other.encode(self.session)), chat.Session())

    def test_an_old_token_expires(self):
        token = self.codec.encode(self.session)
        self.now += state.MAX_AGE + 1
        self.assertEqual(self.codec.decode(token), chat.Session())

    def test_only_the_last_turns_are_kept(self):
        turns = tuple(assistant.Turn(f"q{n}", "a") for n in range(assistant.MAX_HISTORY_TURNS + 3))
        kept = self.codec.decode(self.codec.encode(chat.Session(history=turns))).history
        self.assertEqual(kept, turns[-assistant.MAX_HISTORY_TURNS:])


class RateLimitTests(unittest.TestCase):
    def test_each_visitor_gets_a_budget_per_window(self):
        limit = chat.RateLimit(per_window=2, window=60)
        self.assertTrue(limit.allow("a", now=0))
        self.assertTrue(limit.allow("a", now=1))
        self.assertFalse(limit.allow("a", now=2))
        self.assertTrue(limit.allow("b", now=2))
        self.assertTrue(limit.allow("a", now=61))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.fake = Recorder()
        self.app = server.make_server("127.0.0.1", 0, self.fake.tools(),
                                      chat.RateLimit(per_window=3, window=60), secret=SECRET)
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close)
        self.addCleanup(self.app.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.app.server_port, timeout=5)
        self.addCleanup(connection.close)
        payload = json.dumps(body).encode() if isinstance(body, dict) else body
        sent = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=payload, headers=sent)
        response = connection.getresponse()
        return response, response.read()

    def test_the_home_page_is_the_chat_with_a_copyright(self):
        response, body = self.request("GET", "/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"Copyright", body)

    def test_a_question_returns_the_chart_and_the_state_keeps_the_spot(self):
        _, body = self.request("POST", "/api/ai", {"on": False})
        _, body = self.request("POST", "/api/ask", {"question": "BTN shove 10bb",
                                                    "state": json.loads(body)["state"]})
        data = json.loads(body)
        self.assertEqual(base64.b64decode(data["chart"]), PNG)
        self.request("POST", "/api/ask", {"question": "BB", "state": data["state"]})
        self.assertEqual(self.fake.calls[-2], ("solve", "BB", REQUEST))

    def test_an_example_starts_a_fresh_spot(self):
        _, body = self.request("POST", "/api/ai", {"on": False})
        _, body = self.request("POST", "/api/ask", {"question": "icm 50/30/20 CO 7bb",
                                                    "state": json.loads(body)["state"]})
        _, body = self.request("POST", "/api/ask", {"question": "heads-up SB 12bb", "fresh": True,
                                                    "state": json.loads(body)["state"]})
        self.assertEqual(self.fake.calls[-2], ("solve", "heads-up SB 12bb", None))
        self.assertFalse(json.loads(body)["ai"])  # a fresh spot keeps the AI switch where it was

    def test_the_server_sets_no_cookie(self):
        response, _ = self.request("POST", "/api/new", {})
        self.assertIsNone(response.getheader("Set-Cookie"))

    def test_only_json_posts_are_accepted(self):
        response, _ = self.request("POST", "/api/ask", b"question=x",
                                   {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status, 415)

    def test_an_oversized_body_is_refused(self):
        response, _ = self.request("POST", "/api/image", b"x",
                                   {"Content-Length": str(server.MAX_BODY_BYTES + 1)})
        self.assertEqual(response.status, 413)

    def test_a_visitor_over_the_budget_is_told_to_wait(self):
        statuses = [self.request("POST", "/api/ask", {"question": "BTN shove 10bb"})[0].status
                    for _ in range(4)]
        self.assertEqual(statuses[-1], 429)

    def test_a_bad_image_type_is_refused(self):
        image = base64.b64encode(b"img").decode()
        response, _ = self.request("POST", "/api/image", {"image": image, "mime": "image/svg+xml"})
        self.assertEqual(response.status, 400)

    def test_unknown_paths_are_not_found(self):
        self.assertEqual(self.request("GET", "/nope")[0].status, 404)

    def test_the_logo_is_served_as_a_png(self):
        response, body = self.request("GET", "/static/tamkwai-logo.png")
        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "image/png"))
        self.assertTrue(body.startswith(b"\x89PNG"))
        self.assertIn("max-age", response.getheader("Cache-Control"))

    def test_the_research_page_links_the_paper_pdf(self):
        response, body = self.request("GET", "/research")
        self.assertEqual(response.status, 200)
        self.assertIn(b"Copyright", body)
        for pdf in ("/static/open-limp-fold-20bb.pdf", "/static/open-limp-fold-20bb-th.pdf"):
            with self.subTest(pdf=pdf):
                self.assertIn(pdf.encode(), body)
                response, content = self.request("GET", pdf)
                self.assertEqual((response.status, response.getheader("Content-Type")), (200, "application/pdf"))
                self.assertTrue(content.startswith(b"%PDF"))

    def test_static_files_cannot_leave_the_folder(self):
        for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/static/index.html", "/static/"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0].status, 404)

    def test_the_health_check_answers(self):
        response, body = self.request("GET", "/healthz")
        self.assertEqual((response.status, body), (200, b"ok"))


class DeployTests(unittest.TestCase):
    def start(self, **options):
        self.fake = Recorder()
        self.app = server.make_server("127.0.0.1", 0, self.fake.tools(),
                                      chat.RateLimit(per_window=1, window=60), secret=SECRET, **options)
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close)
        self.addCleanup(self.app.shutdown)

    def request(self, method, path, headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.app.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.request(method, path, body=json.dumps(body) if body else None,
                           headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        response.read()
        return response

    def test_other_hosts_move_to_the_main_domain(self):
        self.start(canonical_host="xn--42c7axbfy7dd.com")
        response = self.request("GET", "/?x=1", {"Host": "tamkwai.com"})
        self.assertEqual(response.status, 301)
        self.assertEqual(response.getheader("Location"), "https://xn--42c7axbfy7dd.com/?x=1")

    def test_the_main_domain_and_the_health_check_are_not_moved(self):
        self.start(canonical_host="xn--42c7axbfy7dd.com")
        self.assertEqual(self.request("GET", "/", {"Host": "xn--42c7axbfy7dd.com"}).status, 200)
        self.assertEqual(self.request("GET", "/healthz", {"Host": "healthcheck.railway.app"}).status, 200)

    def test_behind_a_proxy_the_visitor_is_the_address_the_proxy_added(self):
        self.start(trust_proxy=True)
        ask = {"question": "BTN shove 10bb"}
        first = self.request("POST", "/api/ask", {"X-Forwarded-For": "6.6.6.6, 1.1.1.1"}, ask)
        spoofed = self.request("POST", "/api/ask", {"X-Forwarded-For": "7.7.7.7, 1.1.1.1"}, ask)
        other = self.request("POST", "/api/ask", {"X-Forwarded-For": "2.2.2.2"}, ask)
        self.assertEqual((first.status, spoofed.status, other.status), (200, 429, 200))

    def test_the_whole_site_has_a_ceiling(self):
        self.start(trust_proxy=True, site_limit=chat.RateLimit(per_window=2, window=60))
        statuses = [self.request("POST", "/api/ask", {"X-Forwarded-For": f"9.9.9.{n}"},
                                 {"question": "BTN shove 10bb"}).status for n in range(3)]
        self.assertEqual(statuses, [200, 200, 429])



class WsgiTests(unittest.TestCase):
    """Vercel runs the same routes through the WSGI app instead of http.server."""

    def setUp(self):
        self.fake = Recorder()
        config = server.Config(tools=self.fake.tools(), limit=chat.RateLimit(per_window=5, window=60),
                               site_limit=chat.RateLimit(per_window=50, window=60),
                               codec=state.Codec(SECRET), trust_proxy=True)
        self.app = server.wsgi(config)

    def call(self, method, path, body=None, headers=None, query=""):
        raw = json.dumps(body).encode() if isinstance(body, dict) else (body or b"")
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
                   "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
                   "REMOTE_ADDR": "10.0.0.1", "wsgi.input": io.BytesIO(raw), **(headers or {})}
        seen = {}

        def start_response(status, response_headers):
            seen["status"], seen["headers"] = int(status.split()[0]), dict(response_headers)

        payload = b"".join(self.app(environ, start_response))
        return seen["status"], seen["headers"], payload

    def test_the_page_and_the_health_check(self):
        status, headers, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Copyright", body)
        self.assertEqual(self.call("GET", "/healthz")[2], b"ok")

    def test_a_follow_up_keeps_the_spot_through_the_state(self):
        _, _, body = self.call("POST", "/api/ai", {"on": False})
        _, _, body = self.call("POST", "/api/ask", {"question": "BTN shove 10bb", "state": json.loads(body)["state"]})
        self.call("POST", "/api/ask", {"question": "12bb", "state": json.loads(body)["state"]})
        self.assertEqual(self.fake.calls[-2], ("solve", "12bb", REQUEST))

    def test_plo_payload_survives_the_vercel_wsgi_api_with_a_legacy_fallback(self):
        asked = plo_type.lookup("plo A234 ss23")
        self.fake.reply = SimpleNamespace(kind="plo_type", message=plo_type.answer(asked, "EN"),
                                          note="", found=None, plo=asked)
        _, _, body = self.call("POST", "/api/ai", {"on": False})
        status, _, body = self.call("POST", "/api/ask", {"question": "plo A234 ss23",
                                                          "state": json.loads(body)["state"]})
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["kind"], "plo_type")
        self.assertEqual(data["lines"], [data["plo_fallback"]])
        self.assertIsNone(data["chart"])
        self.assertEqual(data["plo"]["tier"], "Trash")
        self.assertIn("Ace-high connected hand", data["plo"]["type"])
        self.assertIn("rainbow", data["plo"]["miracle"])

    def test_ai_on_wsgi_routes_plo_around_a_model_refusal(self):
        tools = chat.Tools(log=lambda _line: None)
        config = server.Config(tools=tools, limit=chat.RateLimit(per_window=5, window=60),
                               site_limit=chat.RateLimit(per_window=50, window=60),
                               codec=state.Codec(SECRET), trust_proxy=True)
        self.app = server.wsgi(config)
        refusal = lambda *_args: assistant.Crafted("I only handle push/fold", None)
        with mock.patch.object(assistant, "craft", refusal), \
                mock.patch.object(assistant, "api_key", return_value="k"):
            status, _, body = self.call("POST", "/api/ask", {"question": "plo T885"})
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["kind"], "plo_type")
        self.assertEqual(data["plo"]["tier"], "Trash")
        self.assertNotIn("only handle push/fold", " ".join(data["lines"]))

    def test_the_help_reads_the_query_string(self):
        _, _, body = self.call("GET", "/api/help", query="lang=en")
        self.assertIn("Examples", json.loads(body)["text"])

    def test_non_json_and_unknown_methods_are_refused(self):
        self.assertEqual(self.call("POST", "/api/ask", b"x=1", {"CONTENT_TYPE": "text/plain"})[0], 415)
        self.assertEqual(self.call("DELETE", "/api/ask")[0], 405)

    def test_the_visitor_is_the_address_the_proxy_added(self):
        spoofed = {"HTTP_X_FORWARDED_FOR": "6.6.6.6, 1.1.1.1"}
        statuses = [self.call("POST", "/api/ask", {"question": "BTN shove 10bb"}, spoofed)[0] for _ in range(6)]
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(self.call("POST", "/api/ask", {"question": "BTN shove 10bb"},
                                   {"HTTP_X_FORWARDED_FOR": "2.2.2.2"})[0], 200)



class DiscordInviteTests(unittest.TestCase):
    """The website invites the same bot, with the same permissions the bot itself asks for."""

    APP_ID = "1552877762950332417"  # TamKwai on the Discord developer portal

    def test_the_home_page_has_a_discord_button_with_the_logo(self):
        page = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="discord-btn"', page)
        self.assertIn('class="discord-logo"', page)

    def test_the_trust_link_asks_the_question_people_ask(self):
        page = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn(">ชาร์ตนี้แม่นแค่ไหน?</a>", page)
        self.assertNotIn("เทียบกับชาร์ต Jonathan Little", page)

    def test_the_page_has_a_safe_structured_plo_renderer(self):
        page = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function ploPanel(data)", page)
        self.assertIn("data.plo", page)
        self.assertIn("data.plo_fallback", page)
        self.assertIn(".plo-tier", page)
        self.assertNotIn("innerHTML", page)

    def test_every_page_links_the_bot_invite(self):
        sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))
        import bot
        invite = bot.invite_url(int(self.APP_ID)).replace("&", "&amp;")
        for page in (ROOT / "public" / "index.html", ROOT / "scripts" / "web" / "method_template.html"):
            with self.subTest(page=page.name):
                self.assertIn(invite, page.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
