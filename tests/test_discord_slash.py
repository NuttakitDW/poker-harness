"""Checks the slash-command version of the Discord bot that runs as a Vercel function."""

import asyncio
import dataclasses
import io
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from nacl.signing import SigningKey
from vercel.cache.context import set_context

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "discord_bot"))
sys.path.insert(0, str(ROOT / "scripts" / "web"))
import chat  # noqa: E402
import discord_api  # noqa: E402
import preflop  # noqa: E402
import slash  # noqa: E402
import slash_answer  # noqa: E402
import slash_commands  # noqa: E402
import state  # noqa: E402

KEY = SigningKey.generate()
PUBLIC_KEY = KEY.verify_key.encode().hex()
PNG = b"\x89PNG-chart"
SECRET = b"test-secret"
REQUEST = preflop.Request(game="mtt", stack=10, hero="BTN")


def signed(payload: dict, key: SigningKey = KEY, timestamp: str | None = None) -> tuple[dict, bytes]:
    timestamp = timestamp or str(int(time.time()))
    body = json.dumps(payload).encode()
    signature = key.sign(timestamp.encode() + body).signature.hex()
    return {"x-signature-ed25519": signature, "x-signature-timestamp": timestamp}, body


def command(name: str, options: list | None = None, guild: bool = True, resolved: dict | None = None) -> dict:
    payload = {"id": "111", "token": "tok", "application_id": "999", "type": slash.COMMAND,
               "channel_id": "555",
               "data": {"name": name, "options": options or [], **({"resolved": resolved} if resolved else {})}}
    if guild:
        payload["member"] = {"user": {"id": "777"}}
    else:
        payload["user"] = {"id": "778"}
    return payload


class FakeApi:
    """Discord REST stand-in that remembers every call."""

    def __init__(self, defer_error: Exception | None = None, download: bytes = PNG,
                 edit_error: Exception | None = None, edit_failures: int = 10**6) -> None:
        self.deferred: list[tuple] = []
        self.edits: list[tuple] = []
        self.downloads: list[str] = []
        self._defer_error = defer_error
        self._download = download
        self._edit_error = edit_error
        self._edit_failures = edit_failures

    def defer(self, interaction_id: str, token: str, ephemeral: bool) -> None:
        if self._defer_error:
            raise self._defer_error
        self.deferred.append((interaction_id, token, ephemeral))

    def edit_original(self, application_id: str, token: str, content: str, file=None) -> None:
        if self._edit_error and self._edit_failures > 0:
            self._edit_failures -= 1
            raise self._edit_error
        self.edits.append((application_id, token, content, file))

    def download(self, url: str) -> bytes:
        self.downloads.append(url)
        return self._download


def endpoint(api: FakeApi | None = None, public_key: str | None = PUBLIC_KEY):
    jobs: list = []
    done: list = []
    point = slash.Endpoint(public_key=public_key, api=api or FakeApi(), schedule=jobs.append,
                           work=lambda interaction, rest: done.append(interaction))
    return point, jobs, done


class VerifyTests(unittest.TestCase):
    def test_a_real_signature_passes(self):
        headers, body = signed({"type": 1}, timestamp="1700000000")
        self.assertTrue(slash.verify(PUBLIC_KEY, headers["x-signature-ed25519"], "1700000000", body))

    def test_a_changed_body_fails(self):
        headers, body = signed({"type": 1}, timestamp="1700000000")
        self.assertFalse(slash.verify(PUBLIC_KEY, headers["x-signature-ed25519"], "1700000000", body + b" "))

    def test_another_key_fails(self):
        headers, body = signed({"type": 1}, key=SigningKey.generate(), timestamp="1700000000")
        self.assertFalse(slash.verify(PUBLIC_KEY, headers["x-signature-ed25519"], "1700000000", body))

    def test_garbage_fails_instead_of_raising(self):
        self.assertFalse(slash.verify(PUBLIC_KEY, "not-hex", "1", b"{}"))
        self.assertFalse(slash.verify("zz", "00" * 64, "1", b"{}"))
        self.assertFalse(slash.verify(PUBLIC_KEY, "", "", b"{}"))


class InteractionTests(unittest.TestCase):
    def test_reads_a_guild_command(self):
        interaction = slash.Interaction.from_payload(
            command("chart", [{"name": "question", "type": 3, "value": "BTN shove 10bb"}]))
        self.assertEqual(interaction.command, "chart")
        self.assertEqual(interaction.option("question"), "BTN shove 10bb")
        self.assertEqual(interaction.user_id, "777")
        self.assertEqual(interaction.channel_id, "555")
        self.assertEqual((interaction.id, interaction.token, interaction.application_id), ("111", "tok", "999"))

    def test_reads_the_user_in_a_dm(self):
        self.assertEqual(slash.Interaction.from_payload(command("new", guild=False)).user_id, "778")

    def test_missing_option_gives_the_default(self):
        interaction = slash.Interaction.from_payload(command("help"))
        self.assertIsNone(interaction.option("lang"))
        self.assertEqual(interaction.option("lang", "th"), "th")

    def test_finds_the_attached_image(self):
        resolved = {"attachments": {"42": {"url": "https://cdn.discordapp.com/a.png",
                                           "content_type": "image/png", "size": 10}}}
        interaction = slash.Interaction.from_payload(
            command("screenshot", [{"name": "image", "type": 11, "value": "42"}], resolved=resolved))
        self.assertEqual(interaction.attachment("image")["url"], "https://cdn.discordapp.com/a.png")
        self.assertIsNone(interaction.attachment("other"))


class EndpointTests(unittest.TestCase):
    def test_answers_the_ping(self):
        point, jobs, _ = endpoint()
        headers, body = signed({"type": slash.PING})
        self.assertEqual(point.handle("POST", headers, body), (200, {"type": slash.PONG}))
        self.assertEqual(jobs, [])

    def test_rejects_a_bad_signature(self):
        point, _, _ = endpoint()
        headers, body = signed({"type": slash.PING}, key=SigningKey.generate())
        self.assertEqual(point.handle("POST", headers, body)[0], 401)

    def test_rejects_other_methods(self):
        point, _, _ = endpoint()
        self.assertEqual(point.handle("GET", {}, b"")[0], 405)

    def test_refuses_when_the_key_is_missing(self):
        point, _, _ = endpoint(public_key=None)
        headers, body = signed({"type": slash.PING})
        self.assertEqual(point.handle("POST", headers, body)[0], 503)

    def test_rejects_an_old_signature_replayed(self):
        point, jobs, _ = endpoint()
        old = str(int(time.time()) - slash.MAX_SKEW - 5)
        headers, body = signed(command("chart"), timestamp=old)
        self.assertEqual(point.handle("POST", headers, body)[0], 401)
        self.assertEqual(jobs, [])

    def test_a_scheduler_crash_still_answers(self):
        done = []

        def broken(job):
            raise RuntimeError("no loop")

        point = slash.Endpoint(public_key=PUBLIC_KEY, api=FakeApi(), schedule=broken,
                               work=lambda interaction, rest: done.append(interaction))
        headers, body = signed(command("new"))
        self.assertEqual(point.handle("POST", headers, body), (202, None))
        self.assertEqual(len(done), 1)

    def test_rejects_signed_garbage(self):
        point, _, _ = endpoint()
        timestamp = str(int(time.time()))
        body = b"not json"
        signature = KEY.sign(timestamp.encode() + body).signature.hex()
        headers = {"x-signature-ed25519": signature, "x-signature-timestamp": timestamp}
        self.assertEqual(point.handle("POST", headers, body)[0], 400)

    def test_defers_a_chart_publicly_then_works_after(self):
        api = FakeApi()
        point, jobs, done = endpoint(api)
        headers, body = signed(command("chart", [{"name": "question", "type": 3, "value": "BTN 10bb"}]))
        self.assertEqual(point.handle("POST", headers, body), (202, None))
        self.assertEqual(api.deferred, [("111", "tok", False)])
        self.assertEqual(done, [])  # nothing slow runs before Discord hears back
        jobs[0]()
        self.assertEqual(done[0].option("question"), "BTN 10bb")

    def test_help_is_only_shown_to_the_asker(self):
        api = FakeApi()
        point, _, _ = endpoint(api)
        headers, body = signed(command("help"))
        point.handle("POST", headers, body)
        self.assertEqual(api.deferred, [("111", "tok", True)])

    def test_falls_back_to_the_http_answer_when_the_callback_fails(self):
        point, jobs, _ = endpoint(FakeApi(defer_error=OSError("down")))
        headers, body = signed(command("new"))
        self.assertEqual(point.handle("POST", headers, body),
                         (200, {"type": slash.DEFERRED, "data": {"flags": slash.EPHEMERAL}}))
        self.assertEqual(len(jobs), 1)

    def test_rejects_interactions_it_does_not_handle(self):
        point, jobs, _ = endpoint()
        headers, body = signed({**command("chart"), "type": 3})
        self.assertEqual(point.handle("POST", headers, body)[0], 400)
        self.assertEqual(jobs, [])


class WsgiTests(unittest.TestCase):
    def call(self, point, method: str, headers: dict, body: bytes):
        environ = {"REQUEST_METHOD": method, "PATH_INFO": slash.PATH, "CONTENT_LENGTH": str(len(body)),
                   "wsgi.input": io.BytesIO(body)}
        environ.update({"HTTP_" + name.upper().replace("-", "_"): value for name, value in headers.items()})
        seen = {}
        chunks = slash.wsgi(point)(environ, lambda status, pairs: seen.update(status=status, headers=dict(pairs)))
        return seen["status"], seen["headers"], b"".join(chunks)

    def test_pong_over_wsgi(self):
        point, _, _ = endpoint()
        headers, body = signed({"type": slash.PING})
        status, pairs, data = self.call(point, "POST", headers, body)
        self.assertEqual(status, "200 OK")
        self.assertEqual(pairs["Content-Type"], "application/json")
        self.assertEqual(json.loads(data), {"type": 1})

    def test_accepted_has_no_body(self):
        point, _, _ = endpoint()
        headers, body = signed(command("contact"))
        status, _, data = self.call(point, "POST", headers, body)
        self.assertEqual((status, data), ("202 Accepted", b""))

    def test_refuses_a_huge_body_unread(self):
        point, _, _ = endpoint()
        environ = {"REQUEST_METHOD": "POST", "CONTENT_LENGTH": str(slash.MAX_BODY + 1),
                   "wsgi.input": io.BytesIO(b"")}
        seen = {}
        slash.wsgi(point)(environ, lambda status, pairs: seen.update(status=status))
        self.assertTrue(seen["status"].startswith("413"))


class ApiTests(unittest.TestCase):
    def recorder(self, status: int = 204, reply: bytes = b""):
        calls = []

        def send(method, url, headers, body, timeout):
            calls.append(SimpleNamespace(method=method, url=url, headers=headers, body=body, timeout=timeout))
            return status, reply

        return discord_api.Api(send=send), calls

    def test_defer_posts_the_callback(self):
        api, calls = self.recorder()
        api.defer("111", "tok", ephemeral=True)
        self.assertEqual(calls[0].method, "POST")
        self.assertTrue(calls[0].url.endswith("/interactions/111/tok/callback"))
        self.assertEqual(json.loads(calls[0].body), {"type": 5, "data": {"flags": 64}})
        self.assertIn("DiscordBot", calls[0].headers["User-Agent"])
        self.assertLess(calls[0].timeout, 3)  # a late acknowledgement is worthless

    def test_defer_raises_on_refusal(self):
        api, _ = self.recorder(status=400)
        with self.assertRaises(discord_api.DiscordError):
            api.defer("111", "tok", ephemeral=False)

    def test_edit_sends_text_and_png_without_pinging_anyone(self):
        api, calls = self.recorder(status=200)
        api.edit_original("999", "tok", "@everyone hi", ("chart.png", PNG))
        call = calls[0]
        self.assertEqual(call.method, "PATCH")
        self.assertTrue(call.url.endswith("/webhooks/999/tok/messages/@original"))
        self.assertIn("multipart/form-data; boundary=", call.headers["Content-Type"])
        self.assertIn(PNG, call.body)
        self.assertIn(b'name="files[0]"; filename="chart.png"', call.body)
        payload = json.loads(call.body.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["attachments"], [{"id": 0, "filename": "chart.png"}])

    def test_edit_without_a_file_is_json(self):
        api, calls = self.recorder(status=200)
        api.edit_original("999", "tok", "x" * 5000)
        self.assertEqual(calls[0].headers["Content-Type"], "application/json")
        payload = json.loads(calls[0].body)
        self.assertEqual(len(payload["content"]), discord_api.MAX_CONTENT)
        self.assertEqual(payload["attachments"], [])

    def test_download_only_from_discord(self):
        api, calls = self.recorder(status=200, reply=PNG)
        self.assertEqual(api.download("https://cdn.discordapp.com/attachments/1/2/a.png?ex=1"), PNG)
        for url in ("http://cdn.discordapp.com/a.png", "https://evil.example/a.png",
                    "https://cdn.discordapp.com.evil.example/a.png", "file:///etc/passwd"):
            with self.assertRaises(discord_api.DiscordError):
                api.download(url)
        self.assertEqual(len(calls), 1)

    def test_redirects_may_not_leave_discord(self):
        handler = discord_api._DiscordOnlyRedirect()
        request = urllib.request.Request("https://cdn.discordapp.com/a.png")
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(request, None, 302, "Found", {}, "http://169.254.169.254/")
        moved = handler.redirect_request(request, None, 302, "Found", {}, "https://media.discordapp.net/a.png")
        self.assertEqual(moved.full_url, "https://media.discordapp.net/a.png")

    def test_truncation_closes_a_code_block(self):
        text = discord_api.truncate("```\n" + "x" * 3000 + "\n```")
        self.assertEqual(len(text), discord_api.MAX_CONTENT)
        self.assertTrue(text.endswith("```"))
        self.assertEqual(text.count("```") % 2, 0)


class ScheduleTests(unittest.TestCase):
    def tearDown(self):
        set_context(wait_until=None)

    def test_uses_wait_until_when_vercel_gives_one(self):
        waited, done = [], []
        set_context(wait_until=waited.append)
        slash.schedule_after_response(lambda: done.append(1))
        self.assertEqual(done, [])  # not before the response goes out
        asyncio.run(waited[0])
        self.assertEqual(done, [1])

    def test_runs_inline_on_vercel_without_wait_until(self):
        done = []
        with mock.patch.dict(os.environ, {"VERCEL": "1"}):
            slash.schedule_after_response(lambda: done.append(1))
        self.assertEqual(done, [1])

    def test_a_broken_wait_until_does_not_lose_the_job(self):
        def broken(awaitable):
            awaitable.close()
            raise RuntimeError("closed")

        done = []
        set_context(wait_until=broken)
        with mock.patch.dict(os.environ, {"VERCEL": "1"}):
            slash.schedule_after_response(lambda: done.append(1))
        self.assertEqual(done, [1])


class FakeStore:
    def __init__(self) -> None:
        self.items: dict = {}
        self.options: dict = {}

    def get(self, key):
        return self.items.get(key)

    def set(self, key, value, options=None):
        self.items[key] = value
        self.options[key] = options

    def delete(self, key):
        self.items.pop(key, None)


class Recorder:
    """The solver, AI and reader stand-ins used through chat.Tools."""

    def __init__(self) -> None:
        self.solved: list = []
        self.logged: list = []

    def tools(self, vision_key: str | None = "key") -> chat.Tools:
        return chat.Tools(solve=self.solve, answer=self.answer, render=lambda *args: PNG,
                          mario=lambda: b"mario", read_question=lambda data, mime, key: "BTN 10bb",
                          vision_key=lambda: vision_key, log=self.logged.append,
                          place=slash_answer.PLACE)

    def solve(self, question, memory=None):
        self.solved.append((question, memory))
        found = SimpleNamespace(book={}, chart={}, hands=(), lang="TH", request=REQUEST)
        return SimpleNamespace(kind="chart", message=None, note="n", found=found)

    def answer(self, question, solve, history, memory):
        made = solve(question, memory=memory)
        return SimpleNamespace(made=made, say="ok", query=question, history=history)


def context(recorder: Recorder, store: FakeStore | None = None, per_window: int = 12,
            vision_key: str | None = "key"):
    memory = slash_answer.Memory(store or FakeStore(), state.Codec(SECRET), SECRET)
    return slash_answer.Context(tools=recorder.tools(vision_key), memory=memory,
                                limit=chat.RateLimit(per_window=per_window),
                                site_limit=chat.RateLimit(per_window=100))


def interaction(name: str, options: list | None = None, **kwargs) -> slash.Interaction:
    return slash.Interaction.from_payload(command(name, options, **kwargs))


def question(text: str) -> list:
    return [{"name": "question", "type": 3, "value": text}]


class AnswerTests(unittest.TestCase):
    def test_chart_answers_with_the_png_and_quotes_the_question(self):
        recorder = Recorder()
        reply = slash_answer.answer(interaction("chart", question("BTN shove 10bb")), context(recorder), FakeApi())
        self.assertEqual(reply.file, ("chart.png", PNG))
        self.assertTrue(reply.content.startswith("> BTN shove 10bb"))
        self.assertEqual(recorder.logged[0]["server"], "discord")

    def test_the_next_question_remembers_the_spot(self):
        recorder, store = Recorder(), FakeStore()
        ctx = context(recorder, store)
        slash_answer.answer(interaction("chart", question("BTN 10bb")), ctx, FakeApi())
        slash_answer.answer(interaction("chart", question("12bb")), ctx, FakeApi())
        self.assertEqual(recorder.solved[1], ("12bb", REQUEST))
        (key, options), = store.options.items()
        self.assertEqual(options, {"ttl": slash_answer.MEMORY_TTL})
        self.assertNotIn("777", key)  # the cache key does not give away who asked

    def test_memory_is_kept_per_person(self):
        store = FakeStore()
        ctx = context(Recorder(), store)
        slash_answer.answer(interaction("ai", [{"name": "mode", "type": 3, "value": "off"}]), ctx, FakeApi())
        mine = interaction("chart", question("x"))
        theirs = interaction("chart", question("x"), guild=False)
        self.assertFalse(ctx.memory.load(mine).ai)
        self.assertTrue(ctx.memory.load(theirs).ai)

    def test_new_forgets(self):
        store = FakeStore()
        ctx = context(Recorder(), store)
        slash_answer.answer(interaction("ai", [{"name": "mode", "type": 3, "value": "off"}]), ctx, FakeApi())
        reply = slash_answer.answer(interaction("new"), ctx, FakeApi())
        self.assertEqual(reply.content, chat.FORGOT)
        self.assertEqual(store.items, {})

    def test_ai_off_answers_without_the_ai(self):
        recorder = Recorder()
        ctx = context(recorder)
        reply = slash_answer.answer(interaction("ai", [{"name": "mode", "type": 3, "value": "off"}]), ctx, FakeApi())
        self.assertEqual(reply.content, chat.TURNED[False])
        slash_answer.answer(interaction("chart", question("BTN 10bb")), ctx, FakeApi())
        self.assertNotIn("ai_query", recorder.logged[-1])

    def test_empty_or_long_questions_are_refused_before_solving(self):
        recorder = Recorder()
        for text, said in (("   ", chat.EMPTY), ("x" * (chat.MAX_QUESTION_CHARS + 1), chat.TOO_LONG)):
            reply = slash_answer.answer(interaction("chart", question(text)), context(recorder), FakeApi())
            self.assertEqual(reply.content, said)
        self.assertEqual(recorder.solved, [])

    def test_too_many_questions_slow_down(self):
        ctx = context(Recorder(), per_window=1)
        slash_answer.answer(interaction("chart", question("BTN 10bb")), ctx, FakeApi())
        reply = slash_answer.answer(interaction("chart", question("BTN 10bb")), ctx, FakeApi())
        self.assertEqual(reply.content, slash_answer.SLOW_DOWN)

    def test_screenshot_reads_the_image(self):
        resolved = {"attachments": {"42": {"url": "https://cdn.discordapp.com/a.png",
                                           "content_type": "image/png", "size": 10}}}
        api = FakeApi()
        reply = slash_answer.answer(
            interaction("screenshot", [{"name": "image", "type": 11, "value": "42"}], resolved=resolved),
            context(Recorder()), api)
        self.assertEqual(api.downloads, ["https://cdn.discordapp.com/a.png"])
        self.assertIn("อ่านจากรูปได้ว่า: BTN 10bb", reply.content)
        self.assertEqual(reply.file, ("chart.png", PNG))

    def test_screenshot_refuses_what_is_not_an_image(self):
        for attached in ({"url": "https://cdn.discordapp.com/a.pdf", "content_type": "application/pdf", "size": 10},
                         {"url": "https://cdn.discordapp.com/a.png", "content_type": "image/png",
                          "size": chat.MAX_IMAGE_BYTES + 1}):
            api = FakeApi()
            reply = slash_answer.answer(
                interaction("screenshot", [{"name": "image", "type": 11, "value": "42"}],
                            resolved={"attachments": {"42": attached}}),
                context(Recorder()), api)
            self.assertEqual(reply.content, slash_answer.BAD_IMAGE)
            self.assertEqual(api.downloads, [])

    def test_help_fits_in_one_message(self):
        for lang in ("th", "en"):
            reply = slash_answer.answer(interaction("help", [{"name": "lang", "type": 3, "value": lang}]),
                                        context(Recorder()), FakeApi())
            self.assertLessEqual(len(reply.content), discord_api.MAX_CONTENT)
            self.assertTrue(reply.content.startswith("```"))
            self.assertIn("/chart", reply.content)

    def test_privacy_names_vercel_not_railway(self):
        for lang in ("th", "en"):
            reply = slash_answer.answer(interaction("privacy", [{"name": "lang", "type": 3, "value": lang}]),
                                        context(Recorder()), FakeApi())
            self.assertIn("Vercel", reply.content)
            self.assertNotIn("Railway", reply.content)
            self.assertLessEqual(len(reply.content), discord_api.MAX_CONTENT)

    def test_contact(self):
        reply = slash_answer.answer(interaction("contact"), context(Recorder()), FakeApi())
        self.assertIn("nuttakitkundum@gmail.com", reply.content)

    def test_unknown_command(self):
        reply = slash_answer.answer(interaction("nope"), context(Recorder()), FakeApi())
        self.assertEqual(reply.content, slash_answer.UNKNOWN)


class RunTests(unittest.TestCase):
    def test_edits_the_deferred_message(self):
        api = FakeApi()
        slash_answer.run(interaction("contact"), api, context(Recorder()))
        self.assertEqual(api.edits[0][:2], ("999", "tok"))

    def test_a_crash_still_says_sorry(self):
        api = FakeApi()
        ctx = context(Recorder())
        broken = slash_answer.Context(tools=ctx.tools, memory=None, limit=ctx.limit, site_limit=ctx.site_limit)
        slash_answer.run(interaction("new"), api, broken)
        self.assertEqual(api.edits[0][2], chat.FAILED)

    def test_a_failed_edit_does_not_raise(self):
        slash_answer.run(interaction("contact"), FakeApi(edit_error=OSError("down")), context(Recorder()))

    def test_a_rejected_picture_is_retried_as_text(self):
        api = FakeApi(edit_error=discord_api.DiscordError("413"), edit_failures=1)
        slash_answer.run(interaction("chart", question("BTN 10bb")), api, context(Recorder()))
        (_, _, content, file), = api.edits
        self.assertIsNone(file)
        self.assertIn(slash_answer.NO_PICTURE, content)

    def test_a_slow_answer_says_so_in_time(self):
        api = FakeApi()
        ctx = context(Recorder())
        slow = dataclasses.replace(ctx, tools=dataclasses.replace(
            ctx.tools, solve=lambda question, memory=None: time.sleep(1)))
        started = time.perf_counter()
        slash_answer.run(interaction("chart", question("BTN 10bb")), api, slow, seconds=0.05)
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(api.edits[0][2], slash_answer.TOO_SLOW)


class CommandTests(unittest.TestCase):
    def test_every_command_is_answered(self):
        names = {item["name"] for item in slash_commands.COMMANDS}
        self.assertEqual(names, set(slash_answer.ROUTES))

    def test_only_questions_are_public(self):
        self.assertEqual(set(slash.PUBLIC_COMMANDS), {"chart", "screenshot"})

    def test_definitions_fit_discord_limits(self):
        for item in slash_commands.COMMANDS:
            self.assertRegex(item["name"], r"^[a-z0-9_-]{1,32}$")
            self.assertLessEqual(len(item["description"]), 100)
            for option in item.get("options", []):
                self.assertRegex(option["name"], r"^[a-z0-9_-]{1,32}$")
                self.assertLessEqual(len(option["description"]), 100)
            required = [option.get("required", False) for option in item.get("options", [])]
            self.assertEqual(required, sorted(required, reverse=True))  # required options first


class ColdStartTests(unittest.TestCase):
    def test_the_vercel_entry_does_not_load_the_solver_before_discord_is_answered(self):
        code = ("import sys; import api.index; "
                "print(sorted(name for name in ('chat', 'spot_chart', 'server', 'numpy') if name in sys.modules))")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "[]")


if __name__ == "__main__":
    unittest.main()
