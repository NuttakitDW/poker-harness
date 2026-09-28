"""ChatGPT-subscription backend using one local ``codex app-server`` process.

The app-server owns authentication and model access.  Swarm tools remain in this
process as dynamic tools, while Codex itself is confined to a read-only sandbox.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from swarm.openai_backend import LocalTools, WakeInterrupted, tool_definitions

REQUEST_TIMEOUT = 120
TURN_TIMEOUT = 900


class CodexProtocolError(RuntimeError):
    pass


def _dynamic_tools(member_ids: list[str], member_id: str, is_lead: bool) -> list[dict[str, Any]]:
    result = []
    for definition in tool_definitions(member_ids, member_id, is_lead):
        if definition.get("type") != "function":
            continue
        result.append({
            "type": "function",
            "name": definition["name"],
            "description": definition["description"],
            "inputSchema": definition["parameters"],
        })
    return result


class CodexAppServer:
    """Async JSON-RPC client shared by every persona in a swarm."""

    def __init__(self, process: asyncio.subprocess.Process):
        self.process = process
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._sessions: dict[str, "CodexSession"] = {}
        self._turns: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}
        self._completed: dict[tuple[str, str], dict[str, Any]] = {}
        self._items: dict[tuple[str, str], list[tuple[str | None, str]]] = {}
        self._request_tasks: set[asyncio.Task[None]] = set()
        self._stderr_tail: list[str] = []
        self._failure: Exception | None = None
        self._reader = asyncio.create_task(self._read_stdout(), name="codex-app-server-reader")
        self._stderr = asyncio.create_task(self._read_stderr(), name="codex-app-server-stderr")

    @classmethod
    async def start(cls, repo: Path | None = None, disabled_mcp: tuple[str, ...] = ()) -> "CodexAppServer":
        # Strict config makes a typo in a safety override fatal.  Authentication
        # stays in the user's Codex home; no token is read or copied here.
        argv = [
            "codex", "app-server", "--stdio", "--strict-config",
            "-c", "mcp_servers={}",
            "--disable", "shell_tool", "--disable", "unified_exec",
            "--disable", "apps", "--disable", "plugins", "--disable", "hooks",
            "--disable", "multi_agent", "--disable", "browser_use",
            "--disable", "computer_use", "--disable", "image_generation",
            "--disable", "skill_search", "--enable", "skip_host_skill_discovery",
        ]
        for name in disabled_mcp:
            argv.extend(("-c", f"mcp_servers.{name}.enabled=false"))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SystemExit("GPT-6 subscription mode requires the `codex` CLI") from exc
        server = cls(process)
        try:
            await server.request("initialize", {
                "clientInfo": {"name": "deepstack-swarm", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            await server.notify("initialized", {})
            effective = (await server.request("config/read", {
                "cwd": str(repo.resolve()) if repo else None, "includeLayers": False,
            })).get("config", {})
            inherited = tuple(sorted(
                name for name, value in effective.get("mcp_servers", {}).items()
                if value.get("enabled", True)
            ))
            if inherited and not disabled_mcp:
                await server.close()
                return await cls.start(repo, inherited)
            features = effective.get("features", {})
            required_disabled = ("shell_tool", "unified_exec", "apps", "plugins", "hooks", "multi_agent")
            if inherited or any(features.get(name) is not False for name in required_disabled):
                raise CodexProtocolError("could not disable inherited Codex native tools, plugins, or MCP servers")
            if features.get("skip_host_skill_discovery") is not True:
                raise CodexProtocolError("could not disable inherited Codex skills")
        except Exception:
            await server.close()
            raise
        return server

    async def validate(self, models: list[tuple[str, str]], repo: Path) -> None:
        account = await self.request("account/read", {"refreshToken": False})
        if (account.get("account") or {}).get("type") != "chatgpt":
            raise SystemExit("GPT-6 subscription mode requires `codex login` with a ChatGPT account")
        available: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        while True:
            catalog = await self.request("model/list", {
                "includeHidden": True, "limit": 100, "cursor": cursor,
            })
            available.update({
                entry.get("model", entry.get("id")): entry for entry in catalog.get("data", [])
            })
            cursor = catalog.get("nextCursor")
            if not cursor:
                break
        for model, effort in models:
            entry = available.get(model)
            if entry is None:
                raise SystemExit(f"Codex ChatGPT account does not offer model {model!r}")
            efforts = {value.get("reasoningEffort") for value in entry.get("supportedReasoningEfforts", [])}
            if effort not in efforts:
                raise SystemExit(f"Codex model {model!r} does not support reasoning effort {effort!r}")
        # This live response confirms the effective sandbox before a run directory
        # is created. No model turn or filesystem mutation is involved.
        probe_model, _probe_effort = models[0]
        probe = await self.request("thread/start", {
            "cwd": str(repo.resolve()), "model": probe_model, "sandbox": "read-only",
            "approvalPolicy": "never", "ephemeral": True, "dynamicTools": [],
            "developerInstructions": "Configuration probe only.",
            "multiAgentMode": "explicitRequestOnly",
        })
        sandbox = probe.get("sandbox") or {}
        if sandbox.get("type") != "readOnly" or sandbox.get("networkAccess") is not False:
            raise SystemExit("Codex app-server did not enforce the required read-only sandbox")
        if probe.get("approvalPolicy") != "never":
            raise SystemExit("Codex app-server did not enforce approvalPolicy=never")

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._failure is not None:
            raise CodexProtocolError(str(self._failure))
        if self.process.returncode is not None:
            raise CodexProtocolError(self._process_error())
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"id": request_id, "method": method, "params": params})
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await future
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"method": method, "params": params})

    async def _write(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None or self.process.returncode is not None:
            raise CodexProtocolError(self._process_error())
        self.process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
        await self.process.stdin.drain()

    async def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            while line := await self.process.stdout.readline():
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise CodexProtocolError(f"malformed app-server response: {exc}") from exc
                if "id" in message and "method" in message:
                    task = asyncio.create_task(self._handle_server_request(message))
                    self._request_tasks.add(task)
                    task.add_done_callback(self._request_tasks.discard)
                elif "id" in message:
                    future = self._pending.get(message["id"])
                    if future is not None and not future.done():
                        if "error" in message:
                            future.set_exception(CodexProtocolError(str(message["error"])))
                        else:
                            future.set_result(message.get("result") or {})
                elif "method" in message:
                    self._handle_notification(message["method"], message.get("params") or {})
            raise CodexProtocolError(self._process_error())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_all(exc)

    async def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        while line := await self.process.stderr.readline():
            self._stderr_tail = (self._stderr_tail + [line.decode(errors="replace").strip()])[-20:]

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        request_id = message["id"]
        try:
            if message["method"] != "item/tool/call":
                raise CodexProtocolError(f"app-server requested unsupported method {message['method']!r}")
            params = message.get("params") or {}
            session = self._sessions.get(params.get("threadId"))
            if session is None:
                raise CodexProtocolError("dynamic tool call belongs to an unknown thread")
            result = await session.call_tool(params["tool"], params.get("arguments") or {})
            response = {"contentItems": [{"type": "inputText", "text": result}], "success": True}
            await self._write({"id": request_id, "result": response})
        except Exception as exc:
            response = {"contentItems": [{"type": "inputText", "text": f"error: {exc}"}], "success": False}
            await self._write({"id": request_id, "result": response})

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        key = (params.get("threadId", ""), params.get("turnId", ""))
        if method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "agentMessage" and item.get("text", "").strip():
                self._items.setdefault(key, []).append((item.get("phase"), item["text"].strip()))
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            key = (params.get("threadId", ""), turn.get("id", ""))
            future = self._turns.get(key)
            if future is not None and not future.done():
                future.set_result(turn)
            else:
                self._completed[key] = turn

    def _fail_all(self, exc: Exception) -> None:
        self._failure = exc
        for future in [*self._pending.values(), *self._turns.values()]:
            if not future.done():
                future.set_exception(exc)

    def _process_error(self) -> str:
        detail = "; ".join(filter(None, self._stderr_tail[-3:]))
        return f"codex app-server exited{f': {detail}' if detail else ''}"

    async def run_turn(self, thread_id: str, prompt: str, model: str, effort: str) -> tuple[str, dict[str, int], str]:
        response = await self.request("turn/start", {
            "threadId": thread_id, "model": model, "effort": effort,
            "input": [{"type": "text", "text": prompt}],
            "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"},
            "multiAgentMode": "explicitRequestOnly", "disabledPluginIds": [],
        })
        turn_id = response["turn"]["id"]
        key = (thread_id, turn_id)
        future = asyncio.get_running_loop().create_future()
        self._turns[key] = future
        session = self._sessions.get(thread_id)
        if session is not None:
            session.active_turn = turn_id
            if session.interrupt_requested:
                await self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        # A very fast completion can arrive before turn/start's response.
        initial = response.get("turn") or {}
        if initial.get("status") in {"completed", "failed", "interrupted", "cancelled"}:
            future.set_result(initial)
        elif key in self._completed:
            future.set_result(self._completed.pop(key))
        try:
            async with asyncio.timeout(TURN_TIMEOUT):
                turn = await future
        finally:
            self._turns.pop(key, None)
            if session is not None:
                session.active_turn = None
        status = turn.get("status")
        if status in {"interrupted", "cancelled"}:
            raise WakeInterrupted()
        if status != "completed":
            raise CodexProtocolError(f"Codex turn ended with {status}: {turn.get('error')}")
        messages = self._items.pop(key, [])
        final_messages = [text for phase, text in messages if phase == "final_answer"]
        # Current providers may omit phase. The last completed assistant item is
        # the terminal answer; earlier items are progress/commentary.
        text = final_messages[-1] if final_messages else (messages[-1][1] if messages else "")
        return text, {"input_tokens": 0, "output_tokens": 0}, turn_id

    def register(self, thread_id: str, session: "CodexSession") -> None:
        self._sessions[thread_id] = session

    async def close(self) -> None:
        if self.process.returncode is None:
            self.process.terminate()
            try:
                async with asyncio.timeout(5):
                    await self.process.wait()
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in [*self._request_tasks, self._reader, self._stderr]:
            task.cancel()
        await asyncio.gather(*self._request_tasks, self._reader, self._stderr, return_exceptions=True)


class CodexSession:
    def __init__(
        self, *, server: CodexAppServer, model: str, reasoning_effort: str, instructions: str,
        repo: Path, workspace: Path, member_ids: list[str], member_id: str, is_lead: bool,
        thread_id: str | None, team_tool: Callable[[str, dict[str, Any]], Awaitable[str]],
        tool_event: Callable[[str, dict[str, Any]], None], save_thread: Callable[[str], None],
    ):
        self.server = server
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.instructions = instructions
        self.repo = repo
        self.tools = LocalTools(repo, workspace)
        self.member_ids = member_ids
        self.member_id = member_id
        self.is_lead = is_lead
        self.thread_id = thread_id
        self.team_tool = team_tool
        self.tool_event = tool_event
        self.save_thread = save_thread
        self.active_turn: str | None = None
        self.interrupt_requested = False
        self._ready = False

    async def _ensure_thread(self) -> None:
        if self._ready:
            return
        if self.thread_id:
            self.server.register(self.thread_id, self)
            await self.server.request("thread/resume", {
                "threadId": self.thread_id, "cwd": str(self.repo), "model": self.model,
                "sandbox": "read-only", "approvalPolicy": "never",
                "developerInstructions": self.instructions,
            })
            self._ready = True
            return
        response = await self.server.request("thread/start", {
            "cwd": str(self.repo), "model": self.model, "sandbox": "read-only",
            "approvalPolicy": "never", "ephemeral": False,
            "developerInstructions": self.instructions,
            "dynamicTools": _dynamic_tools(self.member_ids, self.member_id, self.is_lead),
            "multiAgentMode": "explicitRequestOnly",
        })
        self.thread_id = response["thread"]["id"]
        self.server.register(self.thread_id, self)
        self.save_thread(self.thread_id)
        self._ready = True

    async def wake(self, prompt: str) -> tuple[str, dict[str, int]]:
        self.interrupt_requested = False
        await self._ensure_thread()
        assert self.thread_id is not None
        text, usage, _turn_id = await self.server.run_turn(
            self.thread_id, prompt, self.model, self.reasoning_effort,
        )
        return text, usage

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        self.tool_event(name, args)
        if name in {"send_message", "team_status", "tell_user"}:
            return await self.team_tool(name, args)
        try:
            return await self.tools.execute(name, args)
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    async def interrupt(self) -> None:
        self.interrupt_requested = True
        if self.thread_id and self.active_turn:
            await self.server.request("turn/interrupt", {
                "threadId": self.thread_id, "turnId": self.active_turn,
            })

    async def close(self) -> None:
        pass
