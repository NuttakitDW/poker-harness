"""The Team: one provider session per persona, woken by mail from the Router.

Each agent gets the built-in research tools (Read, Grep, Bash, WebSearch, ...) plus
an in-process MCP server named `team` with send_message / team_status, and for the
lead, tell_user. Everything an agent does is written to the run's EventLog, which
is what the monitor terminal draws.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import warnings
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from swarm import guard, prompts, provider
from swarm.codex_backend import CodexAppServer, CodexSession
from swarm.openai_backend import OpenAIResponsesSession, WakeInterrupted
from swarm.events import EventLog, write_state
from swarm.roster import LEAD_ID, USER_ID, Member
from swarm.router import Mail, Router

# Read-only and team tools are meant to skip the permission callback; only writes and Bash are judged.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

BUILTIN_TOOLS = ["Read", "Glob", "Grep", "Bash", "Write", "Edit", "WebSearch", "WebFetch"]
AUTO_ALLOWED = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]
TEXT_PREVIEW = 400


@dataclasses.dataclass(frozen=True)
class TeamConfig:
    repo: Path
    workspace: Path
    team_rules: str
    model: str
    lead_model: str
    max_turns_per_wake: int = 40
    deepseek_key: str = ""  # only needed when a model is deepseek-*
    backend: str = "claude"
    mode: str = "default"
    openai_key: str = ""
    reasoning_effort: str = "medium"
    lead_reasoning_effort: str = "high"
    codex_server: CodexAppServer | None = None


def summarize_tool(name: str, tool_input: dict[str, Any]) -> str:
    """One line for the monitor: what the tool was pointed at."""
    for key in ("command", "file_path", "pattern", "query", "url", "path", "to"):
        if key in tool_input:
            return f"{key}={str(tool_input[key])[:160]}"
    return json.dumps(tool_input, ensure_ascii=False)[:160]


def short_tool_name(name: str) -> str:
    return name.removeprefix("mcp__team__")


class Agent:
    def __init__(self, member: Member, swarm: "Swarm"):
        self.member = member
        self.swarm = swarm
        self.client: ClaudeSDKClient | OpenAIResponsesSession | CodexSession | None = None
        self.session_id: str | None = swarm.saved_sessions.get(member.id) if swarm.config.backend == "claude" else None
        self.codex_thread_id: str | None = swarm.saved_codex_threads.get(member.id)
        self.working = False
        self.told_user = False
        self.sent = False
        self.cost_usd = 0.0
        self.turns = 0
        self._session_cost = 0.0  # the SDK reports cost cumulative per connected session

    # -- tools -------------------------------------------------------------
    def _tools(self) -> list:
        router = self.swarm.router
        me = self.member.id
        ids = list(router.members) + ["all"]

        @tool(
            "send_message",
            "Send a message to a teammate (or 'all'). It wakes them and costs a turn from the shared budget.",
            {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "enum": [i for i in ids if i != me]},
                    "message": {"type": "string"},
                },
                "required": ["to", "message"],
            },
        )
        async def send_message(args: dict[str, Any]) -> dict[str, Any]:
            result = router.send(me, args["to"], args["message"])
            self.sent = self.sent or not result.startswith("error")
            return {"content": [{"type": "text", "text": result}], "is_error": result.startswith("error")}

        @tool("team_status", "Who is working, how much mail is queued, and how many turns the swarm has left.", {})
        async def team_status(args: dict[str, Any]) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": self.swarm.status_text()}]}

        tools = [send_message, team_status]
        if self.member.is_lead:

            @tool("tell_user", "Show a message to the user in the chat terminal. The only way the user hears you.",
                  {"message": str})
            async def tell_user(args: dict[str, Any]) -> dict[str, Any]:
                text = args["message"].strip()
                if not text:
                    return {"content": [{"type": "text", "text": "error: empty message"}], "is_error": True}
                self.told_user = True
                self.swarm.log.emit("reply", agent=me, text=text)
                return {"content": [{"type": "text", "text": "shown to the user"}]}

            tools.append(tell_user)
        return tools

    async def _can_use_tool(
        self, name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        cfg = self.swarm.config
        verdict = guard.judge(name, tool_input, cfg.workspace, cfg.repo)
        if verdict.allow:
            return PermissionResultAllow()
        self.swarm.log.emit("notice", agent=self.member.id, text=f"blocked {name}: {verdict.reason}")
        return PermissionResultDeny(message=verdict.reason)

    def _options(self) -> ClaudeAgentOptions:
        cfg = self.swarm.config
        server = create_sdk_mcp_server("team", tools=self._tools())
        team_tools = ["mcp__team__send_message", "mcp__team__team_status"]
        if self.member.is_lead:
            team_tools.append("mcp__team__tell_user")
        model = cfg.lead_model if self.member.is_lead else cfg.model
        return ClaudeAgentOptions(
            system_prompt=prompts.system_prompt(self.member, self.swarm.roster, cfg.team_rules),
            model=model,
            env=provider.env_for(model, cfg.deepseek_key),
            cwd=str(cfg.repo),
            tools=BUILTIN_TOOLS,
            allowed_tools=AUTO_ALLOWED + team_tools,
            mcp_servers={"team": server},
            strict_mcp_config=True,
            setting_sources=[],  # isolated: no user hooks, CLAUDE.md or plugins
            permission_mode="default",
            can_use_tool=self._can_use_tool,
            max_turns=cfg.max_turns_per_wake,
            resume=self.session_id,
        )

    async def _openai_team_tool(self, name: str, args: dict[str, Any]) -> str:
        me = self.member.id
        if name == "send_message":
            result = self.swarm.router.send(me, args["to"], args["message"])
            self.sent = self.sent or not result.startswith("error")
            return result
        if name == "team_status":
            return self.swarm.status_text()
        if name == "tell_user" and self.member.is_lead:
            text = args["message"].strip()
            if not text:
                return "error: empty message"
            self.told_user = True
            self.swarm.log.emit("reply", agent=me, text=text)
            return "shown to the user"
        return f"error: unavailable team tool {name!r}"

    def _openai_tool_event(self, name: str, args: dict[str, Any]) -> None:
        self.swarm.log.emit("tool", agent=self.member.id, name=name, summary=summarize_tool(name, args))

    def _openai_session(self) -> OpenAIResponsesSession:
        cfg = self.swarm.config
        model = cfg.lead_model if self.member.is_lead else cfg.model
        effort = cfg.lead_reasoning_effort if self.member.is_lead else cfg.reasoning_effort
        return OpenAIResponsesSession(
            api_key=cfg.openai_key,
            model=model,
            reasoning_effort=effort,
            instructions=prompts.system_prompt(self.member, self.swarm.roster, cfg.team_rules),
            repo=cfg.repo,
            workspace=cfg.workspace,
            member_ids=list(self.swarm.router.members),
            member_id=self.member.id,
            is_lead=self.member.is_lead,
            history=self.swarm.saved_histories.get(self.member.id),
            team_tool=self._openai_team_tool,
            tool_event=self._openai_tool_event,
            save_history=lambda history: self.swarm.save_history(self.member.id, history),
            max_tool_rounds=cfg.max_turns_per_wake,
        )

    def _codex_session(self) -> CodexSession:
        cfg = self.swarm.config
        if cfg.codex_server is None:
            raise RuntimeError("Codex backend was not initialized")
        return CodexSession(
            server=cfg.codex_server,
            model=cfg.lead_model if self.member.is_lead else cfg.model,
            reasoning_effort=cfg.lead_reasoning_effort if self.member.is_lead else cfg.reasoning_effort,
            instructions=prompts.system_prompt(self.member, self.swarm.roster, cfg.team_rules),
            repo=cfg.repo, workspace=cfg.workspace,
            member_ids=list(self.swarm.router.members), member_id=self.member.id,
            is_lead=self.member.is_lead, thread_id=self.codex_thread_id,
            team_tool=self._openai_team_tool, tool_event=self._openai_tool_event,
            save_thread=lambda thread_id: self.swarm.save_codex_thread(self.member.id, thread_id),
        )

    # -- life cycle ----------------------------------------------------------
    async def run(self) -> None:
        router, log, me = self.swarm.router, self.swarm.log, self.member.id
        while True:
            batch = await router.next_batch(me)
            self.working = True
            self.told_user = False
            self.sent = False
            log.emit("state", agent=me, state="working", detail=f"{len(batch)} message(s)",
                     turns_left=router.turns_left)
            try:
                last_text = await self._wake(prompts.inbox_prompt(batch))
                self._deliver_plain_text(batch, last_text)
            except WakeInterrupted:
                log.emit("notice", agent=me, text="wake stopped by user")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one agent failing must not take the swarm down
                log.emit("error", agent=me, text=f"{type(exc).__name__}: {exc}")
                await self._reset_client()
            finally:
                self.working = False
                log.emit("state", agent=me, state="idle")

    async def _wake(self, prompt: str) -> str:
        """One agent turn; returns the last thing it said in plain text."""
        if self.swarm.config.backend in {"openai", "codex"}:
            if self.client is None:
                self.client = self._codex_session() if self.swarm.config.backend == "codex" else self._openai_session()
            assert isinstance(self.client, (OpenAIResponsesSession, CodexSession))
            last_text, usage = await self.client.wake(prompt)
            if last_text:
                self.swarm.log.emit("text", agent=self.member.id, text=last_text[:TEXT_PREVIEW])
            self.turns += 1
            self.swarm.log.emit(
                "turn_end", agent=self.member.id, cost_usd=0.0, cost_available=False,
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                is_error=False, subtype="success",
            )
            return last_text
        if self.client is None:
            self.client = ClaudeSDKClient(self._options())
            self._session_cost = 0.0
            await self.client.connect()
        await self.client.query(prompt)
        last_text = ""
        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        last_text = block.text.strip()
                        self.swarm.log.emit("text", agent=self.member.id, text=last_text[:TEXT_PREVIEW])
                    elif isinstance(block, ToolUseBlock):
                        self.swarm.log.emit("tool", agent=self.member.id, name=short_tool_name(block.name),
                                            summary=summarize_tool(block.name, block.input))
            elif isinstance(message, ResultMessage):
                self._settle(message)
        return last_text

    def _deliver_plain_text(self, batch: list[Mail], last_text: str) -> None:
        """Models sometimes answer in plain text, which nobody sees. Pass it on.

        The lead's goes to the user. A teammate's goes back to whoever wrote to it,
        but only for real requests: text sent on automatically never triggers another
        automatic send, so two agents cannot bounce plain text back and forth.
        """
        if not last_text:
            return
        me = self.member.id
        if self.member.is_lead:
            from_user = any(m.sender == USER_ID for m in batch)
            if not self.told_user and (from_user or not self.sent):
                self.swarm.log.emit("reply", agent=me, text=last_text)
            return
        if self.sent:
            return
        askers = dict.fromkeys(LEAD_ID if m.sender == USER_ID else m.sender for m in batch if not m.auto)
        for asker in askers:
            if asker != me:
                self.swarm.router.send(me, asker, last_text, auto=True)

    def _settle(self, result: ResultMessage) -> None:
        self.turns += 1
        session_total = result.total_cost_usd or 0.0
        cost = max(0.0, session_total - self._session_cost)
        self._session_cost = session_total
        self.cost_usd += cost
        self.session_id = result.session_id
        self.swarm.save_session(self.member.id, result.session_id)
        self.swarm.log.emit("turn_end", agent=self.member.id, cost_usd=cost, total_usd=self.cost_usd,
                            is_error=result.is_error, subtype=result.subtype)

    async def interrupt(self) -> None:
        if self.client is not None and self.working:
            await self.client.interrupt()

    async def _reset_client(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            try:
                if isinstance(client, (OpenAIResponsesSession, CodexSession)):
                    await client.close()
                else:
                    await client.disconnect()
            except Exception:
                pass

    async def close(self) -> None:
        await self._reset_client()


class Swarm:
    def __init__(self, roster: tuple[Member, ...], config: TeamConfig, log: EventLog,
                 turn_budget: int, saved_sessions: dict[str, str] | None = None,
                 saved_histories: dict[str, list[dict[str, Any]]] | None = None,
                 saved_codex_threads: dict[str, str] | None = None):
        self.roster = roster
        self.config = config
        self.log = log
        self.router = Router(roster, log, turn_budget)
        self.saved_sessions = dict(saved_sessions or {})
        self.saved_histories = dict(saved_histories or {})
        self.saved_codex_threads = dict(saved_codex_threads or {})
        self.agents = {m.id: Agent(m, self) for m in roster}
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self.log.emit("run_start", members=[
            {"id": m.id, "name": m.name, "role": m.short_role, "lead": m.is_lead} for m in self.roster
        ], budget=self.router.turns_left, model=self.config.model, lead_model=self.config.lead_model,
            mode=self.config.mode, backend=self.config.backend)
        self._tasks = [asyncio.create_task(a.run(), name=a.member.id) for a in self.agents.values()]

    def save_session(self, member_id: str, session_id: str) -> None:
        self.saved_sessions = {**self.saved_sessions, member_id: session_id}
        self._write_state()

    def save_history(self, member_id: str, history: list[dict[str, Any]]) -> None:
        self.saved_histories = {**self.saved_histories, member_id: history}
        self._write_state()

    def save_codex_thread(self, member_id: str, thread_id: str) -> None:
        self.saved_codex_threads = {**self.saved_codex_threads, member_id: thread_id}
        self._write_state()

    def _write_state(self) -> None:
        write_state(self.log.run_dir, {
            "mode": self.config.mode,
            "backend": self.config.backend,
            "model": self.config.model,
            "lead_model": self.config.lead_model,
            "sessions": {"claude": self.saved_sessions},
            "openai_histories": self.saved_histories,
            "codex_threads": self.saved_codex_threads,
        })

    def status_text(self) -> str:
        pending = self.router.pending()
        lines = [f"turns left: {self.router.turns_left}"]
        for mid, agent in self.agents.items():
            state = "working" if agent.working else "idle"
            cost = f"${agent.cost_usd:.2f}" if self.config.backend == "claude" else "cost unavailable"
            lines.append(f"{mid:10} {state:8} queued={pending[mid]} turns={agent.turns} {cost}")
        return "\n".join(lines)

    def total_cost(self) -> float:
        return sum(a.cost_usd for a in self.agents.values())

    async def stop_all(self) -> int:
        await asyncio.gather(*(a.interrupt() for a in self.agents.values()), return_exceptions=True)
        # Clear after interrupts so a tool completing at the same moment cannot
        # leave fresh mail that unexpectedly wakes an agent after /stop.
        dropped = self.router.clear()
        self.log.emit("notice", text=f"stopped all agents, dropped {dropped} queued message(s)")
        return dropped

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.gather(*(a.close() for a in self.agents.values()), return_exceptions=True)
        if self.config.codex_server is not None:
            await self.config.codex_server.close()


def on_events(log: EventLog, callback: Callable[[dict[str, Any]], None]) -> EventLog:
    """Wrap an EventLog so the chat terminal also sees each event as it is written."""

    class Tee(EventLog):
        def emit(self, type_: str, **fields: Any) -> dict[str, Any]:
            event = super().emit(type_, **fields)
            callback(event)
            return event

    return Tee(log.run_dir)
