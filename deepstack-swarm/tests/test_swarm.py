"""Checks the swarm plumbing that needs no model: roster, guard, router, event log, monitor state."""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOME))

from swarm import guard, prompts, provider  # noqa: E402
from swarm.codex_backend import CodexProtocolError, CodexSession  # noqa: E402
from swarm.events import EventLog, current_run, new_run, read_new  # noqa: E402
from swarm.openai_backend import LocalTools, OpenAIResponsesSession, WakeInterrupted  # noqa: E402
from swarm.monitor_state import MonitorState, apply  # noqa: E402
from swarm.roster import LEAD_ID, USER_ID, load_roster  # noqa: E402
from swarm.router import Mail, Router  # noqa: E402

ROSTER = load_roster(HOME / "souls")


class ProviderTest(unittest.TestCase):
    def test_claude_models_keep_the_default_login(self) -> None:
        self.assertEqual(provider.env_for("claude-sonnet-5", key="k"), {})

    def test_deepseek_models_go_to_the_anthropic_compatible_endpoint(self) -> None:
        env = provider.env_for("deepseek-flash", key="sk-test")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], provider.DEEPSEEK_BASE_URL)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-test")
        # background calls that name a small model must stay on DeepSeek too
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "deepseek-flash")

    def test_missing_key_fails_with_the_variable_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "DEEPSEEK_API_KEY"):
                provider.deepseek_key(Path(tmp), environ={})

    def test_key_is_read_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text("OTHER=1\nDEEPSEEK_API_KEY='sk-file'\n")
            self.assertEqual(provider.deepseek_key(Path(tmp), environ={}), "sk-file")

    def test_openai_key_is_read_without_leaking_it_in_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("OPENAI_API_KEY='sk-openai-file'\n")
            self.assertEqual(provider.openai_key(root, environ={}), "sk-openai-file")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "OPENAI_API_KEY") as raised:
                provider.openai_key(Path(tmp), environ={})
            self.assertNotIn("sk-", str(raised.exception))

    def test_default_model_is_deepseek(self) -> None:
        from swarm import chat
        self.assertTrue(provider.is_deepseek(chat.DEFAULT_MODEL))


class TempRun(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.log = EventLog(new_run(self.tmp / "runs"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def events(self) -> list[dict]:
        return read_new(self.log.path, 0)[0]


class RosterTest(unittest.TestCase):
    def test_all_ten_authors_with_bowling_first(self) -> None:
        self.assertEqual(len(ROSTER), 10)
        self.assertEqual(ROSTER[0].id, LEAD_ID)
        self.assertTrue(ROSTER[0].is_lead)
        self.assertEqual(sum(m.is_lead for m in ROSTER), 1)

    def test_ids_are_surnames_and_roles_are_short(self) -> None:
        ids = {m.id for m in ROSTER}
        self.assertEqual(ids, {"bowling", "bard", "burch", "davis", "johanson", "lisy",
                               "moravcik", "morrill", "schmid", "waugh"})
        for m in ROSTER:
            self.assertTrue(m.short_role)
            self.assertNotIn("(", m.short_role)

    def test_system_prompt_has_soul_rules_team_and_lead_duties_only_for_lead(self) -> None:
        lead, other = ROSTER[0], ROSTER[1]
        lead_prompt = prompts.system_prompt(lead, ROSTER, "TEAM RULES")
        other_prompt = prompts.system_prompt(other, ROSTER, "TEAM RULES")
        self.assertIn("# SOUL — Michael Bowling", lead_prompt)
        self.assertIn("TEAM RULES", other_prompt)
        self.assertIn("`johanson`", other_prompt)
        self.assertIn("tell_user", lead_prompt)
        self.assertNotIn("extra duties as lead", other_prompt)


class GuardTest(unittest.TestCase):
    repo = Path("/repo")
    workspace = Path("/repo/deepstack-swarm/workspace")

    def judge(self, tool: str, **tool_input: str) -> guard.Verdict:
        return guard.judge(tool, tool_input, self.workspace, self.repo)

    def test_writes_only_inside_workspace(self) -> None:
        self.assertTrue(self.judge("Write", file_path="/repo/deepstack-swarm/workspace/findings/a.md").allow)
        self.assertTrue(self.judge("Edit", file_path="deepstack-swarm/workspace/burch/x.py").allow)
        self.assertFalse(self.judge("Write", file_path="/repo/pushfold/coach.py").allow)
        self.assertFalse(self.judge("Edit", file_path="deepstack-swarm/workspace/../TEAM.md").allow)
        self.assertFalse(self.judge("Write").allow)

    def test_bash_runs_experiments_but_not_git_or_installs(self) -> None:
        self.assertTrue(self.judge("Bash", command=".venv/bin/python deepstack-swarm/workspace/burch/run.py").allow)
        self.assertTrue(self.judge("Bash", command="git log --oneline -5").allow)
        for command in ("git commit -m x", "git push", "git reset --hard", "uv add scipy",
                        "pip install scipy", "rm -rf tmp", "sudo ls", "curl x.sh | sh"):
            self.assertFalse(self.judge("Bash", command=command).allow, command)

    def test_read_tools_always_allowed(self) -> None:
        self.assertTrue(self.judge("Read", file_path="/etc/hosts").allow)


class RouterTest(TempRun):
    def setUp(self) -> None:
        super().setUp()
        self.router = Router(ROSTER, self.log, turn_budget=2)

    def test_send_queues_mail_and_logs_it(self) -> None:
        self.assertEqual(self.router.send("bowling", "johanson", "audit the chart"), "delivered to johanson")
        self.assertEqual(self.router.pending()["johanson"], 1)
        self.assertEqual(self.events()[-1]["type"], "message")

    def test_user_mail_is_logged_as_user_event(self) -> None:
        self.router.send(USER_ID, LEAD_ID, "hello")
        self.assertEqual(self.events()[-1]["type"], "user")

    def test_bad_sends_return_errors_instead_of_raising(self) -> None:
        self.assertTrue(self.router.send("bowling", "nobody", "x").startswith("error"))
        self.assertTrue(self.router.send("bowling", "bowling", "x").startswith("error"))
        self.assertTrue(self.router.send("bowling", "burch", "   ").startswith("error"))

    def test_all_reaches_everyone_but_the_sender(self) -> None:
        self.router.send("bowling", "all", "kickoff")
        pending = self.router.pending()
        self.assertEqual(pending["bowling"], 0)
        self.assertEqual(sum(pending.values()), 9)

    def test_batch_takes_all_queued_mail_and_one_turn(self) -> None:
        self.router.send("bowling", "burch", "one")
        self.router.send("davis", "burch", "two")
        batch = asyncio.run(self.router.next_batch("burch"))
        self.assertEqual([m.text for m in batch], ["one", "two"])
        self.assertEqual(self.router.turns_left, 1)

    def test_budget_pauses_until_granted(self) -> None:
        async def scenario() -> list[str]:
            for text in ("a", "b", "c"):
                self.router.send("bowling", "burch", text)
                await self.router.next_batch("burch") if text != "c" else None
            waiting = asyncio.create_task(self.router.next_batch("burch"))
            await asyncio.sleep(0.05)
            self.assertFalse(waiting.done())  # paused: budget is 0
            self.router.grant(1)
            return [m.text for m in await asyncio.wait_for(waiting, 1)]

        self.assertEqual(asyncio.run(scenario()), ["c"])
        notices = [e["text"] for e in self.events() if e["type"] == "notice"]
        self.assertTrue(any("paused" in n for n in notices))

    def test_clear_drops_queued_mail(self) -> None:
        self.router.send("bowling", "all", "x")
        self.assertEqual(self.router.clear(), 9)
        self.assertEqual(sum(self.router.pending().values()), 0)

    def test_inbox_prompt_marks_direct_user_mail(self) -> None:
        text = prompts.inbox_prompt([Mail("user", "hi", direct=True), Mail("burch", "result")])
        self.assertIn("[from user] (direct from the user)", text)
        self.assertIn("[from burch]\nresult", text)


class EventLogTest(TempRun):
    def test_current_run_points_at_newest(self) -> None:
        runs = self.tmp / "runs"
        second = new_run(runs)
        self.assertEqual(current_run(runs), second)

    def test_read_new_resumes_from_offset_and_skips_partial_lines(self) -> None:
        self.log.emit("notice", text="one")
        events, offset = read_new(self.log.path, 0)
        self.assertEqual(len(events), 1)
        with self.log.path.open("a") as f:
            f.write(json.dumps({"type": "notice", "text": "two"}) + "\n" + '{"type": "half')
        events, offset2 = read_new(self.log.path, offset)
        self.assertEqual([e["text"] for e in events], ["two"])
        self.assertEqual(read_new(self.log.path, offset2), ([], offset2))


class MonitorStateTest(unittest.TestCase):
    members = [{"id": "bowling", "name": "Michael Bowling", "role": "PI", "lead": True},
               {"id": "burch", "name": "Neil Burch", "role": "Solver"}]

    def replay(self, *events: dict) -> MonitorState:
        state = MonitorState()
        for event in events:
            state = apply(state, event)
        return state

    def test_run_start_builds_agents_and_budget(self) -> None:
        state = self.replay({"type": "run_start", "ts": 1, "members": self.members, "budget": 40})
        self.assertEqual([a.id for a in state.agents], ["bowling", "burch"])
        self.assertEqual(state.turns_left, 40)

    def test_work_cycle_updates_state_cost_and_feeds(self) -> None:
        state = self.replay(
            {"type": "run_start", "ts": 1, "members": self.members, "budget": 40},
            {"type": "user", "ts": 2, "sender": "user", "to": "bowling", "text": "go"},
            {"type": "state", "ts": 3, "agent": "burch", "state": "working", "turns_left": 39},
            {"type": "tool", "ts": 4, "agent": "burch", "name": "Bash", "summary": "command=ls"},
            {"type": "turn_end", "ts": 5, "agent": "burch", "cost_usd": 0.25},
            {"type": "reply", "ts": 6, "agent": "bowling", "text": "done"},
        )
        burch = state.agents[1]
        self.assertEqual((burch.state, burch.turns, burch.cost), ("working", 1, 0.25))
        self.assertEqual(burch.last, "Bash  command=ls")
        self.assertEqual(state.turns_left, 39)
        self.assertEqual([line.kind for line in state.traffic], ["user", "reply"])
        self.assertEqual(state.total_cost(), 0.25)

    def test_apply_never_mutates_the_old_state(self) -> None:
        before = self.replay({"type": "run_start", "ts": 1, "members": self.members, "budget": 5})
        after = apply(before, {"type": "state", "ts": 2, "agent": "burch", "state": "working"})
        self.assertEqual(before.agents[1].state, "idle")
        self.assertEqual(after.agents[1].state, "working")

    def test_unknown_events_and_agents_are_ignored(self) -> None:
        state = self.replay({"type": "run_start", "ts": 1, "members": self.members},
                            {"type": "mystery", "ts": 2},
                            {"type": "turn_end", "ts": 3, "agent": "ghost", "cost_usd": 9})
        self.assertEqual(state.total_cost(), 0)

    def test_openai_run_records_backend_for_cost_display(self) -> None:
        state = self.replay({"type": "run_start", "ts": 1, "members": self.members,
                             "backend": "openai", "model": "gpt-6-sol"})
        self.assertEqual(state.backend, "openai")
        from swarm.monitor import header

        text = header(state, 2).plain
        self.assertIn("cost unavailable", text)
        self.assertNotIn("$0.00", text)


class AgentDeliveryTest(TempRun):
    """Plain-text answers reach someone, and never ping-pong."""

    def setUp(self) -> None:
        super().setUp()
        from swarm.team import Swarm, TeamConfig

        config = TeamConfig(repo=HOME.parent, workspace=self.tmp / "ws", team_rules="", model="m", lead_model="m")
        self.swarm = Swarm(ROSTER, config, self.log, turn_budget=10)

    def deliver(self, agent_id: str, batch: list[Mail], text: str, sent: bool = False) -> None:
        agent = self.swarm.agents[agent_id]
        agent.sent, agent.told_user = sent, False
        agent._deliver_plain_text(batch, text)

    def test_teammate_text_goes_back_to_the_asker(self) -> None:
        self.deliver("burch", [Mail("bowling", "what is CFR+?")], "regret floors at zero")
        mail = self.swarm.router.inboxes["bowling"].get_nowait()
        self.assertEqual((mail.sender, mail.text, mail.auto), ("burch", "regret floors at zero", True))

    def test_direct_user_mail_is_answered_through_the_lead(self) -> None:
        self.deliver("johanson", [Mail("user", "how big is the game?", direct=True)], "tiny")
        self.assertEqual(self.swarm.router.pending()["bowling"], 1)

    def test_forwarded_text_is_never_forwarded_again(self) -> None:
        self.deliver("davis", [Mail("burch", "fyi", auto=True)], "noted")
        self.assertEqual(sum(self.swarm.router.pending().values()), 0)

    def test_nothing_forwarded_when_the_agent_already_sent_a_message(self) -> None:
        self.deliver("burch", [Mail("bowling", "q")], "done", sent=True)
        self.assertEqual(sum(self.swarm.router.pending().values()), 0)

    def test_lead_plain_text_is_shown_to_the_user(self) -> None:
        self.deliver("bowling", [Mail("user", "hi")], "hello")
        self.assertEqual(self.events()[-1]["type"], "reply")

    def test_cost_is_the_difference_between_cumulative_session_totals(self) -> None:
        from claude_agent_sdk import ResultMessage

        agent = self.swarm.agents["burch"]
        for total in (0.10, 0.25):
            agent._settle(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                                        num_turns=1, session_id="s", total_cost_usd=total))
        self.assertAlmostEqual(agent.cost_usd, 0.25)
        self.assertEqual([round(e["cost_usd"], 2) for e in self.events() if e["type"] == "turn_end"], [0.10, 0.15])


class ChatStatusTest(unittest.TestCase):
    members = MonitorStateTest.members

    def text(self, *events: dict, now: float = 20.0) -> str:
        from swarm.chat import status_line

        state = MonitorState()
        for event in ({"type": "run_start", "ts": 0, "members": self.members, "budget": 40},) + events:
            state = apply(state, event)
        return "".join(part for _, part in status_line(state, now))

    def test_idle_shows_budget_and_cost(self) -> None:
        text = self.text()
        self.assertIn("idle", text)
        self.assertIn("turns left 40", text)

    def test_lead_working_shows_thinking_time_and_current_action(self) -> None:
        text = self.text({"type": "state", "ts": 8, "agent": "bowling", "state": "working"},
                         {"type": "tool", "ts": 9, "agent": "bowling", "name": "WebFetch", "summary": "url=x"})
        self.assertIn("Bowling is thinking 12s", text)
        self.assertIn("WebFetch url=x", text)

    def test_old_action_from_a_previous_turn_is_not_shown(self) -> None:
        text = self.text({"type": "tool", "ts": 1, "agent": "bowling", "name": "Read", "summary": "old"},
                         {"type": "state", "ts": 8, "agent": "bowling", "state": "working"})
        self.assertNotIn("old", text)

    def test_teammates_working_are_listed(self) -> None:
        text = self.text({"type": "state", "ts": 8, "agent": "burch", "state": "working"})
        self.assertIn("team working", text)
        self.assertIn("burch", text)

    def test_paused_budget_is_called_out(self) -> None:
        text = self.text({"type": "notice", "ts": 5, "text": "paused", "turns_left": 0})
        self.assertIn("/more", text)

    def test_gpt6_mode_uses_astra_lead_and_sol_teammates(self) -> None:
        from swarm import chat

        args = chat.parse_args(["--mode", "gpt6"])
        mode, backend, model, lead = chat._resolved(args, {})
        self.assertEqual((mode, backend, model, lead),
                         ("gpt6", "codex", "gpt-6-sol", "gpt-6-astra"))

    def test_gpt6_api_is_an_explicit_separate_mode(self) -> None:
        from swarm import chat

        resolved = chat._resolved(chat.parse_args(["--mode", "gpt6-api"]), {})
        self.assertEqual(resolved, ("gpt6-api", "openai", "gpt-6-sol", "gpt-6-astra"))

    def test_plain_resume_restores_provider_and_models(self) -> None:
        from swarm import chat

        args = chat.parse_args(["--resume"])
        resolved = chat._resolved(args, {
            "mode": "gpt6", "backend": "openai", "model": "gpt-6-sol", "lead_model": "gpt-6-astra",
        })
        self.assertEqual(resolved, ("gpt6", "codex", "gpt-6-sol", "gpt-6-astra"))

    def test_models_cannot_be_silently_sent_to_the_wrong_provider(self) -> None:
        from swarm import chat

        with self.assertRaisesRegex(SystemExit, "requires OpenAI"):
            chat._resolved(chat.parse_args(["--mode", "gpt6", "--model", "deepseek-flash"]), {})
        with self.assertRaisesRegex(SystemExit, "require --mode gpt6"):
            chat._resolved(chat.parse_args(["--model", "gpt-6-sol"]), {})

    def test_gpt6_status_omits_unknown_dollar_cost(self) -> None:
        from swarm.chat import status_line

        state = apply(MonitorState(), {"type": "run_start", "ts": 0, "members": self.members, "budget": 2})
        text = "".join(part for _, part in status_line(state, 1, cost_available=False))
        self.assertIn("cost unavailable", text)
        self.assertNotIn("$", text)


class FakeResponses:
    def __init__(self, responses: list[SimpleNamespace] | None = None):
        self.queue = list(responses or [])
        self.calls: list[dict] = []
        self.block = asyncio.Event()

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.queue:
            return self.queue.pop(0)
        await self.block.wait()
        return self.queue.pop(0)


class FakeOpenAI:
    def __init__(self, responses: list[SimpleNamespace] | None = None):
        self.responses = FakeResponses(responses)

    async def close(self) -> None:
        pass


def fake_response(output: list[dict], text: str = "", input_tokens: int = 3,
                  output_tokens: int = 2, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        output=output,
        output_text=text,
        status=status,
        incomplete_details=SimpleNamespace(reason="max_output_tokens") if status == "incomplete" else None,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class OpenAIBackendTest(TempRun):
    def session(self, client: FakeOpenAI, *, team_tool=None, history=None, saved=None,
                member_id: str = "burch", is_lead: bool = False) -> OpenAIResponsesSession:
        async def default_team(name: str, args: dict) -> str:
            return f"{name}: ok"

        return OpenAIResponsesSession(
            api_key="unused", model="gpt-6-sol", reasoning_effort="medium", instructions="test",
            repo=HOME.parent, workspace=self.tmp / "workspace", member_ids=["bowling", "burch"],
            member_id=member_id, is_lead=is_lead, history=history, team_tool=team_tool or default_team,
            tool_event=lambda name, args: None, save_history=(saved or (lambda value: None)), client=client,
        )

    def test_tool_loop_is_local_history_and_reports_usage(self) -> None:
        async def scenario():
            used = []
            saved = []

            async def team(name: str, args: dict) -> str:
                used.append((name, args))
                return "delivered to bowling"

            client = FakeOpenAI([
                fake_response([{"type": "function_call", "name": "send_message", "call_id": "c1",
                                "arguments": '{"to":"bowling","message":"done"}'}]),
                fake_response([{"type": "message", "role": "assistant", "content": []}], "finished", 4, 1),
            ])
            session = self.session(client, team_tool=team, saved=lambda value: saved.append(value))
            text, usage = await session.wake("work")
            return text, usage, used, saved, client.responses.calls

        text, usage, used, saved, calls = asyncio.run(scenario())
        self.assertEqual(text, "finished")
        self.assertEqual(usage, {"input_tokens": 7, "output_tokens": 3})
        self.assertEqual(used, [("send_message", {"to": "bowling", "message": "done"})])
        self.assertEqual(calls[0]["store"], False)
        self.assertEqual(calls[0]["reasoning"], {"effort": "medium"})
        self.assertTrue(any(item.get("type") == "function_call_output" for item in calls[1]["input"]))
        self.assertEqual(saved[0][-1]["type"], "function_call_output")
        self.assertEqual(saved[-1][-1]["type"], "message")

    def test_saved_history_is_supplied_on_resume(self) -> None:
        history = [{"role": "user", "content": "old"},
                   {"type": "message", "role": "assistant", "content": []}]
        client = FakeOpenAI([fake_response([], "new")])
        asyncio.run(self.session(client, history=history).wake("continue"))
        self.assertEqual(client.responses.calls[0]["input"][:2], history)
        self.assertEqual(client.responses.calls[0]["input"][2]["content"], "continue")

    def test_incomplete_response_is_a_controlled_error(self) -> None:
        client = FakeOpenAI([fake_response([], status="incomplete")])
        with self.assertRaisesRegex(RuntimeError, "max_output_tokens"):
            asyncio.run(self.session(client).wake("too long"))

    def test_interrupt_cancels_one_wake_and_session_can_wake_again(self) -> None:
        async def scenario():
            client = FakeOpenAI()
            session = self.session(client)
            wake = asyncio.create_task(session.wake("wait"))
            while session.current is None:
                await asyncio.sleep(0)
            await session.interrupt()
            with self.assertRaises(WakeInterrupted):
                await wake
            client.responses.queue.append(fake_response([], "awake"))
            return await session.wake("again")

        self.assertEqual(asyncio.run(scenario())[0], "awake")

    def test_interrupt_durably_closes_an_in_progress_tool_call(self) -> None:
        async def scenario():
            started = asyncio.Event()
            blocker = asyncio.Event()
            saved = []
            invocations = 0

            async def team(name: str, args: dict) -> str:
                nonlocal invocations
                invocations += 1
                started.set()
                await blocker.wait()
                return "delivered"

            client = FakeOpenAI([
                fake_response([{"type": "function_call", "name": "send_message", "call_id": "blocked",
                                "arguments": '{"to":"bowling","message":"x"}'}]),
            ])
            session = self.session(client, team_tool=team, saved=lambda value: saved.append(value))
            wake = asyncio.create_task(session.wake("start"))
            await started.wait()
            await session.interrupt()
            with self.assertRaises(WakeInterrupted):
                await wake
            client.responses.queue.append(fake_response(
                [{"type": "message", "role": "assistant", "content": []}], "next"))
            text, _ = await session.wake("new mail")
            return text, invocations, saved

        text, invocations, saved = asyncio.run(scenario())
        self.assertEqual((text, invocations), ("next", 1))
        self.assertEqual(saved[-1][-1]["type"], "message")
        cancelled = [item for checkpoint in saved for item in checkpoint
                     if item.get("type") == "function_call_output" and "cancelled" in item.get("output", "")]
        self.assertTrue(cancelled)

    def test_local_tools_deny_writes_outside_workspace_and_shell_bypasses(self) -> None:
        async def scenario():
            tools = LocalTools(HOME.parent, self.tmp / "workspace")
            with self.assertRaises(PermissionError):
                await tools.execute("write_file", {"path": str(self.tmp / "outside.txt"), "content": "x"})
            with self.assertRaises(PermissionError):
                await tools.execute("run_command", {"command": "sh -c 'echo x > /tmp/swarm-bypass'"})
            with self.assertRaises(PermissionError):
                await tools.execute("run_command", {"command": "python -c 'open(\"/tmp/x\",\"w\").write(\"x\")'"})

        asyncio.run(scenario())

    def test_local_tools_hide_credentials_and_runtime_state(self) -> None:
        async def scenario():
            repo = self.tmp / "repo"
            workspace = repo / "deepstack-swarm" / "workspace"
            runtime = repo / "deepstack-swarm" / "runs" / "current"
            workspace.mkdir(parents=True)
            runtime.mkdir(parents=True)
            (repo / ".env").write_text("OPENAI_API_KEY=never-show-this\n")
            (runtime / "state.json").write_text('{"secret":"never-show-this"}')
            (repo / "safe.txt").write_text("safe marker\n")
            tools = LocalTools(repo, workspace)
            for path in (".env", "deepstack-swarm/runs/current/state.json"):
                with self.assertRaises(PermissionError):
                    await tools.execute("read_file", {"path": path})
            listing = await tools.execute("glob_files", {"pattern": "**/*"})
            result = await tools.execute("search_text", {"pattern": "never-show-this", "path": "."})
            return listing, result

        listing, result = asyncio.run(scenario())
        self.assertNotIn(".env", listing)
        self.assertNotIn("state.json", listing)
        self.assertNotIn("never-show-this", result)

    def test_subprocess_output_is_streamed_to_a_hard_cap(self) -> None:
        async def scenario():
            tools = LocalTools(HOME.parent, self.tmp / "workspace")
            return await tools._run([sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"])

        result = asyncio.run(scenario())
        self.assertIn("[truncated]", result)
        self.assertLessEqual(len(result), 32_020)

    @unittest.skipUnless(sys.platform == "darwin", "command file sandbox is macOS-specific")
    def test_python_command_cannot_read_env_or_runtime_state(self) -> None:
        async def scenario():
            with tempfile.TemporaryDirectory(dir=HOME / "workspace") as tmp:
                workspace = Path(tmp)
                secret = workspace / ".env.agent-test"
                runtime = HOME / "runs" / "agent-test-secret.json"
                secret.write_text("command-env-secret")
                runtime.parent.mkdir(exist_ok=True)
                runtime.write_text("command-runtime-secret")
                script = workspace / "probe.py"
                script.write_text(
                    "from pathlib import Path\n"
                    f"for path in ({str(secret)!r}, {str(runtime)!r}):\n"
                    "    try:\n"
                    "        print(Path(path).read_text())\n"
                    "    except OSError:\n"
                    "        print('blocked')\n"
                )
                try:
                    tools = LocalTools(HOME.parent, workspace)
                    command = ".venv-swarm/bin/python " + shlex.quote(str(script.relative_to(HOME.parent)))
                    return await tools.execute("run_command", {"command": command})
                finally:
                    runtime.unlink(missing_ok=True)

        result = asyncio.run(scenario())
        self.assertEqual(result.splitlines(), ["blocked", "blocked"])
        self.assertNotIn("command-env-secret", result)
        self.assertNotIn("command-runtime-secret", result)

    @unittest.skipUnless(sys.platform == "darwin", "command file sandbox is macOS-specific")
    def test_workspace_experiments_can_use_repo_virtualenv(self) -> None:
        async def scenario():
            with tempfile.TemporaryDirectory(dir=HOME / "workspace") as tmp:
                workspace = Path(tmp)
                script = workspace / "experiment.py"
                script.write_text("import numpy, pokerkit\nprint(numpy.__name__, pokerkit.__name__)\n")
                tools = LocalTools(HOME.parent, workspace)
                command = ".venv/bin/python " + shlex.quote(str(script.relative_to(HOME.parent)))
                return await tools.execute("run_command", {"command": command})

        self.assertEqual(asyncio.run(scenario()).strip(), "numpy pokerkit")

    def test_mocked_lead_worker_lead_round_trip(self) -> None:
        from swarm.team import Swarm, TeamConfig

        async def scenario():
            config = TeamConfig(repo=HOME.parent, workspace=self.tmp / "workspace", team_rules="",
                                model="gpt-6-sol", lead_model="gpt-6-astra", backend="openai",
                                mode="gpt6", openai_key="unused")
            swarm = Swarm(ROSTER, config, self.log, turn_budget=5)
            lead, worker = swarm.agents["bowling"], swarm.agents["burch"]
            lead_client = FakeOpenAI([
                fake_response([{"type": "function_call", "name": "send_message", "call_id": "lead-1",
                                "arguments": '{"to":"burch","message":"calculate it"}'}]),
                fake_response([], "delegated"),
            ])
            worker_client = FakeOpenAI([
                fake_response([{"type": "function_call", "name": "send_message", "call_id": "worker-1",
                                "arguments": '{"to":"bowling","message":"answer is 42"}'}]),
                fake_response([], "sent"),
            ])
            lead.client = self.session(lead_client, team_tool=lead._openai_team_tool,
                                       member_id="bowling", is_lead=True)
            worker.client = self.session(worker_client, team_tool=worker._openai_team_tool)
            await lead._wake("from user")
            worker_batch = await swarm.router.next_batch("burch")
            await worker._wake(prompts.inbox_prompt(worker_batch))
            lead_batch = await swarm.router.next_batch("bowling")
            lead_client.responses.queue.extend([
                fake_response([{"type": "function_call", "name": "tell_user", "call_id": "lead-2",
                                "arguments": '{"message":"final: 42"}'}]),
                fake_response([], "done"),
            ])
            await lead._wake(prompts.inbox_prompt(lead_batch))

        asyncio.run(scenario())
        traffic = [(event.get("sender"), event.get("to"), event.get("text"))
                   for event in self.events() if event["type"] == "message"]
        self.assertEqual(traffic, [("bowling", "burch", "calculate it"),
                                   ("burch", "bowling", "answer is 42")])
        self.assertEqual([event["text"] for event in self.events() if event["type"] == "reply"], ["final: 42"])


class FakeCodexServer:
    def __init__(self):
        self.sessions = {}
        self.started = 0
        self.resumed = []
        self.interrupted = []
        self.turns = {}
        self.resume_error = None

    async def request(self, method, params):
        if method == "thread/resume":
            if self.resume_error:
                raise self.resume_error
            self.resumed.append(params["threadId"])
            return {"thread": {"id": params["threadId"]}}
        if method == "thread/start":
            self.started += 1
            return {"thread": {"id": f"thread-{self.started}"}}
        if method == "turn/interrupt":
            self.interrupted.append((params["threadId"], params["turnId"]))
            return {}
        raise AssertionError(method)

    def register(self, thread_id, session):
        self.sessions[thread_id] = session

    async def run_turn(self, thread_id, prompt, model, effort):
        session = self.sessions[thread_id]
        count = self.turns.get(session.member_id, 0)
        self.turns[session.member_id] = count + 1
        if session.member_id == "bowling" and count == 0:
            await session.call_tool("send_message", {"to": "burch", "message": "calculate it"})
            text = "delegated"
        elif session.member_id == "burch":
            await session.call_tool("send_message", {"to": "bowling", "message": "answer is 42"})
            text = "sent"
        else:
            await session.call_tool("tell_user", {"message": "final: 42"})
            text = "done"
        return text, {"input_tokens": 0, "output_tokens": 0}, f"turn-{count}"

    async def close(self):
        pass


class CodexBackendTest(TempRun):
    def test_session_resumes_saved_thread_and_stop_interrupts_active_turn(self) -> None:
        async def scenario():
            server = FakeCodexServer()

            async def team(name, args):
                return "ok"

            session = CodexSession(
                server=server, model="gpt-6-sol", reasoning_effort="medium", instructions="test",
                repo=HOME.parent, workspace=self.tmp / "workspace", member_ids=["bowling", "burch"],
                member_id="burch", is_lead=False, thread_id="saved-thread", team_tool=team,
                tool_event=lambda name, args: None, save_thread=lambda value: None,
            )
            await session._ensure_thread()
            session.active_turn = "active-turn"
            await session.interrupt()
            return server

        server = asyncio.run(scenario())
        self.assertEqual(server.resumed, ["saved-thread"])
        self.assertEqual(server.interrupted, [("saved-thread", "active-turn")])

    def test_resume_failure_does_not_silently_replace_the_saved_thread(self) -> None:
        async def scenario():
            server = FakeCodexServer()
            server.resume_error = CodexProtocolError("saved thread missing")

            async def team(name, args):
                return "ok"

            session = CodexSession(
                server=server, model="gpt-6-sol", reasoning_effort="medium", instructions="test",
                repo=HOME.parent, workspace=self.tmp / "workspace", member_ids=["bowling", "burch"],
                member_id="burch", is_lead=False, thread_id="saved-thread", team_tool=team,
                tool_event=lambda name, args: None, save_thread=lambda value: None,
            )
            with self.assertRaisesRegex(CodexProtocolError, "saved thread missing"):
                await session._ensure_thread()
            return server.started, session.thread_id

        self.assertEqual(asyncio.run(scenario()), (0, "saved-thread"))

    def test_pending_turn_start_honors_stop_and_final_text_excludes_commentary(self) -> None:
        async def scenario():
            from swarm.codex_backend import CodexAppServer

            server = object.__new__(CodexAppServer)
            server._sessions = {}
            server._turns = {}
            server._completed = {}
            server._items = {("thread", "turn"): [
                ("commentary", "working on it"), ("final_answer", "final only"),
            ]}
            calls = []

            async def request(method, params):
                calls.append(method)
                if method == "turn/start":
                    return {"turn": {"id": "turn", "status": "inProgress"}}
                if method == "turn/interrupt":
                    server._handle_notification("turn/completed", {
                        "threadId": "thread", "turn": {"id": "turn", "status": "interrupted"},
                    })
                    return {}
                raise AssertionError(method)

            server.request = request
            session = SimpleNamespace(active_turn=None, interrupt_requested=True)
            server._sessions["thread"] = session
            with self.assertRaises(WakeInterrupted):
                await CodexAppServer.run_turn(server, "thread", "work", "gpt-6-sol", "medium")

            session.interrupt_requested = False
            async def complete_request(method, params):
                return {"turn": {"id": "turn-2", "status": "completed"}}
            server.request = complete_request
            server._items[("thread", "turn-2")] = [
                ("commentary", "draft"), ("final_answer", "final only"),
            ]
            text, _, _ = await CodexAppServer.run_turn(server, "thread", "work", "gpt-6-sol", "medium")
            return calls, text

        calls, text = asyncio.run(scenario())
        self.assertEqual(calls, ["turn/start", "turn/interrupt"])
        self.assertEqual(text, "final only")

    def test_mocked_subscription_lead_worker_lead_round_trip(self) -> None:
        from swarm.team import Swarm, TeamConfig

        async def scenario():
            server = FakeCodexServer()
            config = TeamConfig(repo=HOME.parent, workspace=self.tmp / "workspace", team_rules="",
                                model="gpt-6-sol", lead_model="gpt-6-astra", backend="codex",
                                mode="gpt6", codex_server=server)
            swarm = Swarm(ROSTER, config, self.log, turn_budget=5)
            lead, worker = swarm.agents["bowling"], swarm.agents["burch"]
            await lead._wake("from user")
            await worker._wake(prompts.inbox_prompt(await swarm.router.next_batch("burch")))
            await lead._wake(prompts.inbox_prompt(await swarm.router.next_batch("bowling")))

        asyncio.run(scenario())
        traffic = [(event.get("sender"), event.get("to"), event.get("text"))
                   for event in self.events() if event["type"] == "message"]
        self.assertEqual(traffic, [("bowling", "burch", "calculate it"),
                                   ("burch", "bowling", "answer is 42")])
        self.assertEqual([event["text"] for event in self.events() if event["type"] == "reply"], ["final: 42"])

    def test_protocol_failure_fails_pending_requests(self) -> None:
        async def scenario():
            future = asyncio.get_running_loop().create_future()
            # _fail_all is the common path used by malformed JSON and process EOF.
            server = object.__new__(__import__("swarm.codex_backend", fromlist=["CodexAppServer"]).CodexAppServer)
            server._pending = {1: future}
            server._turns = {}
            server._failure = None
            server._fail_all(CodexProtocolError("malformed app-server response"))
            return await future

        with self.assertRaisesRegex(CodexProtocolError, "malformed"):
            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
