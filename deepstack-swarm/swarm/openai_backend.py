"""OpenAI Responses backend and its bounded local research tools.

The guard is a policy check, not an operating-system sandbox. Commands are
therefore also parsed without a shell and limited to read-only programs, plus
Python scripts stored in the swarm workspace.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import shlex
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from swarm import guard

MAX_OUTPUT = 32_000
MAX_FILE = 200_000
COMMAND_TIMEOUT = 30
REQUEST_TIMEOUT = 120
READ_ONLY_COMMANDS = frozenset({"git"})
READ_ONLY_GIT = frozenset({"log", "rev-parse", "status", "ls-files", "ls-tree"})
SECRET_ENV_MARKERS = ("API_KEY", "AUTH_TOKEN", "ACCESS_TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


class WakeInterrupted(Exception):
    """The user stopped this wake; the persistent agent loop may continue."""


def _function(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "strict": True,
    }


def tool_definitions(member_ids: list[str], me: str, is_lead: bool) -> list[dict[str, Any]]:
    ids = [member_id for member_id in member_ids if member_id != me] + ["all"]
    tools = [
        _function("send_message", "Send a message to a teammate, or to all teammates.", {
            "to": {"type": "string", "enum": ids}, "message": {"type": "string"},
        }, ["to", "message"]),
        _function("team_status", "Show agent state, queued mail, and remaining turns.", {}, []),
        _function("read_file", "Read a UTF-8 text file in the repository.", {
            "path": {"type": "string"},
        }, ["path"]),
        _function("glob_files", "List repository files matching a glob pattern.", {
            "pattern": {"type": "string"},
        }, ["pattern"]),
        _function("search_text", "Search repository text with ripgrep.", {
            "pattern": {"type": "string"}, "path": {"type": "string"},
        }, ["pattern", "path"]),
        _function("run_command", "Run a bounded research command. Shell operators are unavailable.", {
            "command": {"type": "string"},
        }, ["command"]),
        _function("write_file", "Write UTF-8 text inside the swarm workspace.", {
            "path": {"type": "string"}, "content": {"type": "string"},
        }, ["path", "content"]),
        _function("edit_file", "Replace one exact text occurrence in a swarm workspace file.", {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
        }, ["path", "old", "new"]),
        {"type": "web_search"},
    ]
    if is_lead:
        tools.insert(2, _function("tell_user", "Show a message to the user in the chat terminal.", {
            "message": {"type": "string"},
        }, ["message"]))
    return tools


class LocalTools:
    def __init__(self, repo: Path, workspace: Path):
        self.repo = repo.resolve()
        self.workspace = workspace.resolve()

    def _is_sensitive(self, path: Path) -> bool:
        try:
            parts = path.resolve().relative_to(self.repo).parts
        except ValueError:
            return True
        if any(part == ".git" or part.startswith(".env") for part in parts):
            return True
        return any(parts[index:index + 2] == ("deepstack-swarm", "runs")
                   for index in range(max(0, len(parts) - 1)))

    def _read_path(self, value: str) -> Path:
        path = self._repo_path(value)
        if self._is_sensitive(path):
            raise PermissionError("credentials and swarm runtime state are unavailable to agents")
        return path

    def _repo_path(self, value: str) -> Path:
        path = Path(value)
        path = path if path.is_absolute() else self.repo / path
        path = path.resolve()
        try:
            path.relative_to(self.repo)
        except ValueError as exc:
            raise ValueError(f"path is outside repository: {value}") from exc
        return path

    def _write_path(self, value: str, tool: str) -> Path:
        verdict = guard.judge(tool, {"file_path": value}, self.workspace, self.repo)
        if not verdict.allow:
            raise PermissionError(verdict.reason)
        path = Path(value)
        path = (path if path.is_absolute() else self.repo / path).resolve()
        if self._is_sensitive(path):
            raise PermissionError("credential and runtime-state paths cannot be written by agents")
        return path

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        if name == "read_file":
            path = self._read_path(args["path"])
            data = path.read_text(encoding="utf-8")
            return data[:MAX_FILE] + ("\n[truncated]" if len(data) > MAX_FILE else "")
        if name == "glob_files":
            pattern = args["pattern"]
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                raise ValueError("glob must be relative to the repository")
            paths = (path for path in self.repo.glob(pattern) if not self._is_sensitive(path))
            return "\n".join(str(path.relative_to(self.repo)) for path in list(paths)[:1000])
        if name == "search_text":
            target = self._read_path(args["path"])
            return await self._run([
                "rg", "--line-number", "--max-count", "200",
                "--glob", "!**/.env*", "--glob", "!**/.git/**",
                "--glob", "!deepstack-swarm/runs/**", "--", args["pattern"], str(target),
            ])
        if name == "run_command":
            return await self._command(args["command"])
        if name == "write_file":
            if len(args["content"]) > MAX_FILE:
                raise ValueError(f"write exceeds the {MAX_FILE}-character limit")
            path = self._write_path(args["path"], "Write")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return f"wrote {len(args['content'])} characters to {path.relative_to(self.repo)}"
        if name == "edit_file":
            path = self._write_path(args["path"], "Edit")
            text = path.read_text(encoding="utf-8")
            if not args["old"] or text.count(args["old"]) != 1:
                raise ValueError("old text must occur exactly once")
            path.write_text(text.replace(args["old"], args["new"], 1), encoding="utf-8")
            return f"edited {path.relative_to(self.repo)}"
        raise KeyError(name)

    async def _command(self, command: str) -> str:
        verdict = guard.judge("Bash", {"command": command}, self.workspace, self.repo)
        if not verdict.allow:
            raise PermissionError(verdict.reason)
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ValueError(f"invalid command: {exc}") from exc
        if not argv:
            raise ValueError("empty command")
        executable = Path(argv[0]).name
        if executable in {"python", "python3"} or executable.startswith("python3."):
            if "/" in argv[0]:
                candidate = Path(argv[0]) if Path(argv[0]).is_absolute() else self.repo / argv[0]
                try:
                    relative_executable = Path(os.path.abspath(candidate)).relative_to(self.repo)
                except ValueError as exc:
                    raise PermissionError("Python executable paths must be inside the repository") from exc
                if relative_executable.parts[:2] not in ((".venv", "bin"), (".venv-swarm", "bin")):
                    raise PermissionError("Python must use the repo or swarm virtual environment")
            if len(argv) < 2 or argv[1].startswith("-"):
                raise PermissionError("Python commands must name a script in the swarm workspace")
            script = self._repo_path(argv[1])
            if not guard.inside(script, self.workspace, self.repo):
                raise PermissionError("Python scripts must be inside the swarm workspace")
        elif executable not in READ_ONLY_COMMANDS:
            raise PermissionError(f"command {executable!r} is not in the bounded command set")
        elif "/" in argv[0]:
            raise PermissionError("read-only commands must be invoked by name")
        elif executable == "git":
            if len(argv) < 2 or argv[1] not in READ_ONLY_GIT or any(arg in {"-o", "--output"} or
                                                                   arg.startswith("--output=") for arg in argv[2:]):
                raise PermissionError("only non-output git inspection commands are available")
        return await self._run(self._sandboxed(argv))

    def _sandboxed(self, argv: list[str]) -> list[str]:
        """Deny command reads of credentials/runtime state where macOS supports it."""
        sandbox = shutil.which("sandbox-exec")
        if sys.platform != "darwin" or not sandbox:
            if Path(argv[0]).name.startswith("python"):
                raise PermissionError("Python command execution requires the macOS sandbox")
            return argv
        rules = ["(version 1)", "(allow default)"]
        denied = [(self.repo / ".env", "literal"),
                  (self.repo / "deepstack-swarm" / "runs", "subpath")]
        denied.extend((path, "literal") for path in self.repo.rglob(".env*") if path.is_file())
        for path, operation in dict.fromkeys((path.resolve(), operation) for path, operation in denied):
            escaped = str(path).replace('"', '\\"')
            rules.append(f'(deny file-read-data ({operation} "{escaped}"))')
        return [sandbox, "-p", "".join(rules), *argv]

    async def _run(self, argv: list[str]) -> str:
        try:
            clean_env = {key: value for key, value in os.environ.items()
                         if not any(marker in key.upper() for marker in SECRET_ENV_MARKERS)
                         and not key.upper().endswith("_API")}
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=self.repo, env=clean_env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise ValueError(f"command not found: {argv[0]}") from exc
        output = bytearray()
        truncated = False
        try:
            assert process.stdout is not None
            async with asyncio.timeout(COMMAND_TIMEOUT):
                while chunk := await process.stdout.read(8192):
                    remaining = MAX_OUTPUT - len(output)
                    if remaining > 0:
                        output.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
                await process.wait()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        except TimeoutError:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise TimeoutError(f"command timed out after {COMMAND_TIMEOUT}s") from None
        text = bytes(output).decode("utf-8", errors="replace")
        suffix = f"\n[exit {process.returncode}]" if process.returncode else ""
        if truncated:
            text += "\n[truncated]"
        return text + suffix


class OpenAIResponsesSession:
    """A local-history Responses tool loop for one swarm persona."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        reasoning_effort: str,
        instructions: str,
        repo: Path,
        workspace: Path,
        member_ids: list[str],
        member_id: str,
        is_lead: bool,
        history: list[dict[str, Any]] | None,
        team_tool: Callable[[str, dict[str, Any]], Awaitable[str]],
        tool_event: Callable[[str, dict[str, Any]], None],
        save_history: Callable[[list[dict[str, Any]]], None],
        max_tool_rounds: int = 40,
        client: Any = None,
    ):
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT)
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.instructions = instructions
        self.tools = tool_definitions(member_ids, member_id, is_lead)
        self.local = LocalTools(repo, workspace)
        self.history = list(history or [])
        self.team_tool = team_tool
        self.tool_event = tool_event
        self.save_history = save_history
        self.max_tool_rounds = max_tool_rounds
        self.current: asyncio.Task[Any] | None = None
        self.wake_task: asyncio.Task[Any] | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    async def wake(self, prompt: str) -> tuple[str, dict[str, int]]:
        self.wake_task = asyncio.current_task()
        self._idle.clear()
        items = list(self.history)
        usage = {"input_tokens": 0, "output_tokens": 0}
        try:
            pending = self._pending_calls(items)
            if pending:
                await self._execute_calls(items, pending)
            items.append({"role": "user", "content": prompt})
            for _ in range(self.max_tool_rounds):
                self.current = asyncio.create_task(self.client.responses.create(
                    model=self.model,
                    instructions=self.instructions,
                    input=items,
                    tools=self.tools,
                    reasoning={"effort": self.reasoning_effort},
                    store=False,
                    max_output_tokens=8_000,
                ))
                try:
                    async with asyncio.timeout(REQUEST_TIMEOUT):
                        response = await self.current
                finally:
                    self.current = None
                status = getattr(response, "status", None)
                if status != "completed":
                    details = getattr(response, "incomplete_details", None)
                    reason = getattr(details, "reason", None) or status or "unknown"
                    raise RuntimeError(f"OpenAI response did not complete: {reason}")
                response_usage = getattr(response, "usage", None)
                usage["input_tokens"] += int(getattr(response_usage, "input_tokens", 0) or 0)
                usage["output_tokens"] += int(getattr(response_usage, "output_tokens", 0) or 0)
                output = [self._dump(item) for item in getattr(response, "output", [])]
                for item in output:
                    if item.get("type") == "web_search_call":
                        self.tool_event("web_search", {"status": item.get("status", "")})
                items.extend(output)
                calls = [item for item in output if item.get("type") == "function_call"]
                if not calls:
                    self._checkpoint(items)
                    return str(getattr(response, "output_text", "") or "").strip(), usage
                await self._execute_calls(items, calls)
            raise RuntimeError(f"tool loop exceeded {self.max_tool_rounds} rounds")
        except asyncio.CancelledError:
            raise WakeInterrupted() from None
        finally:
            self.current = None
            self.wake_task = None
            self._idle.set()

    def _checkpoint(self, items: list[dict[str, Any]]) -> None:
        self.history = list(items)
        self.save_history(self.history)

    @staticmethod
    def _pending_calls(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        completed = {item.get("call_id") for item in items if item.get("type") == "function_call_output"}
        return [item for item in items
                if item.get("type") == "function_call" and item.get("call_id") not in completed]

    async def _execute_calls(self, items: list[dict[str, Any]], calls: list[dict[str, Any]]) -> None:
        for index, call in enumerate(calls):
            try:
                self.current = asyncio.create_task(self._invoke(call))
                try:
                    result = await self.current
                finally:
                    self.current = None
            except asyncio.CancelledError:
                for cancelled in calls[index:]:
                    items.append({
                        "type": "function_call_output", "call_id": cancelled["call_id"],
                        "output": "error: cancelled by user",
                    })
                self._checkpoint(items)
                raise WakeInterrupted() from None
            items.append({"type": "function_call_output", "call_id": call["call_id"], "output": result})
            # A send or write may already have happened. Persist its paired output
            # before another API request or tool can be interrupted.
            self._checkpoint(items)

    async def _invoke(self, call: dict[str, Any]) -> str:
        name = call["name"]
        try:
            args = json.loads(call.get("arguments") or "{}")
            self.tool_event(name, args)
            if name in {"send_message", "team_status", "tell_user"}:
                return await self.team_tool(name, args)
            return await self.local.execute(name, args)
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    @staticmethod
    def _dump(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        if hasattr(item, "model_dump"):
            return item.model_dump(exclude_none=True)
        raise TypeError(f"unsupported Responses output item: {type(item).__name__}")

    async def interrupt(self) -> None:
        task = self.wake_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(self._idle.wait(), 5)
            except TimeoutError:
                pass

    async def close(self) -> None:
        await self.interrupt()
        close = getattr(self.client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
