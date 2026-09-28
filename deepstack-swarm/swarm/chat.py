"""The Chat terminal: you talk to the lead (bowling); the lead runs the team.

Plain text goes to bowling. Commands:
  /to <id> <text>   write to one agent directly
  /status           who is working, queued mail, turns left, cost
  /more [n]         grant n more agent turns (default: the starting budget)
  /stop             interrupt every agent and drop queued mail
  /team             list the members
  /quit             shut the swarm down (the run stays on disk; --resume picks it up)
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import time

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from swarm import provider, theme
from swarm.codex_backend import CodexAppServer
from swarm.events import EventLog, current_run, new_run, read_state
from swarm.monitor_state import MonitorState, apply
from swarm.roster import LEAD_ID, USER_ID, load_roster
from swarm.team import Swarm, TeamConfig, on_events

HOME = Path(__file__).resolve().parents[1]
REPO = HOME.parent
DEFAULT_MODEL = "deepseek-flash"  # DeepSeek V4.1 Flash; pass --model claude-sonnet-5 for Claude
GPT6_MEMBER_MODEL = "gpt-6-sol"
GPT6_LEAD_MODEL = "gpt-6-astra"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STATUS_REFRESH = 0.25
BAR = "bg:#0B0E16"


def status_line(board: MonitorState, now: float, cost_available: bool = True) -> list[tuple[str, str]]:
    """The bar under the prompt: what the lead is doing, who else is busy, budget and cost."""
    lead = next((a for a in board.agents if a.id == LEAD_ID), None)
    others = [a.id for a in board.agents if a.state == "working" and a.id != LEAD_ID]
    spin = SPINNER[int(now / STATUS_REFRESH) % len(SPINNER)]
    parts: list[tuple[str, str]] = []
    if lead is not None and lead.state == "working":
        parts.append((f"{BAR} {theme.SIGNAL} bold", f" {spin} Bowling is thinking {int(now - lead.since)}s"))
        if lead.last and lead.last_at >= lead.since:
            parts.append((f"{BAR} {theme.ASH}", f"  {' '.join(lead.last.split())[:70]}"))
    elif others:
        parts.append((f"{BAR} {theme.SIGNAL}", f" {spin} team working"))
    elif board.turns_left == 0:
        parts.append((f"{BAR} {theme.BRONZE}", " paused: turn budget used up, type /more"))
    else:
        parts.append((f"{BAR} {theme.ASH}", " idle"))
    if others:
        parts.append((f"{BAR} {theme.BRONZE}", f"   {', '.join(others)}"))
    turns = "-" if board.turns_left is None else str(board.turns_left)
    cost = f"${board.total_cost():.2f}" if cost_available else "cost unavailable"
    parts.append((f"{BAR} {theme.ASH}", f"   turns left {turns}   {cost} "))
    return parts


class ChatView:
    """Prints the events the user should see in the chat terminal."""

    def __init__(self, console: Console, names: dict[str, str], cost_available: bool = True):
        self.console = console
        self.names = names
        self.board = MonitorState()
        self.cost_available = cost_available

    def status(self) -> list[tuple[str, str]]:
        return status_line(self.board, time.time(), self.cost_available)

    def __call__(self, event: dict[str, Any]) -> None:
        self.board = apply(self.board, event)
        kind = event["type"]
        if kind == "reply":
            body = Markdown(event["text"])
            title = Text(f" {self.names.get(event['agent'], event['agent'])} ", style=theme.LEAD)
            self.console.print(Panel(body, title=title, title_align="left", border_style=theme.SIGNAL))
        elif kind == "message" and event["sender"] == LEAD_ID:
            line = Text.assemble(("  bowling -> ", theme.ASH), (event["to"], theme.BRONZE),
                                 (f"  {event['text'][:110]}", theme.ASH))
            self.console.print(line, overflow="ellipsis", no_wrap=True)
        elif kind == "notice" and "agent" not in event:
            self.console.print(Text(f"  [{event['text']}]", style=theme.BRONZE))
        elif kind == "error":
            self.console.print(Text(f"  error in {event['agent']}: {event['text']}", style=theme.ERROR))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="swarm chat", description="Talk to the DeepStack swarm lead.")
    p.add_argument("--mode", choices=("default", "gpt6", "gpt6-api"), default=None,
                   help="gpt6 uses the Codex ChatGPT subscription; gpt6-api uses OPENAI_API_KEY billing")
    p.add_argument("--model", default=None, help="model for the nine teammates")
    p.add_argument("--lead-model", default=None,
                   help="model for bowling (same as --model normally; gpt6 preset: gpt-6-astra)")
    p.add_argument("--turns", type=int, default=40, help="agent turns before the swarm pauses")
    p.add_argument("--resume", action="store_true", help="continue the last run and its agent sessions")
    return p.parse_args(argv)


def help_text() -> str:
    return (__doc__ or "").split("Commands:", 1)[-1].rstrip()


async def handle_command(line: str, swarm: Swarm, console: Console, budget: int) -> bool:
    """Run a /command; returns False when the chat should end."""
    cmd, _, rest = line[1:].partition(" ")
    if cmd in ("quit", "exit", "q"):
        return False
    if cmd == "to":
        target, _, text = rest.strip().partition(" ")
        result = swarm.router.send(USER_ID, target, text, direct=True)
        if result.startswith("error"):
            console.print(Text(f"  {result}", style=theme.ERROR))
    elif cmd == "status":
        total = (f"total ${swarm.total_cost():.2f}" if swarm.config.backend == "claude" else
                 "subscription usage unavailable" if swarm.config.backend == "codex" else
                 "API cost unavailable")
        console.print(Text(swarm.status_text() + f"\n{total}", style=theme.ASH))
    elif cmd == "more":
        swarm.router.grant(int(rest) if rest.strip().isdigit() else budget)
    elif cmd == "stop":
        await swarm.stop_all()
    elif cmd == "team":
        for m in swarm.roster:
            console.print(Text.assemble((f"  {m.id:10}", theme.SIGNAL), (f"{m.name:20}", theme.PALE),
                                        (m.short_role, theme.ASH)))
    else:
        console.print(Text(help_text(), style=theme.ASH))
    return True


def _deepseek_key(args: argparse.Namespace) -> str:
    models = (args.model or DEFAULT_MODEL, args.lead_model or args.model or DEFAULT_MODEL)
    return provider.deepseek_key(REPO) if any(map(provider.is_deepseek, models)) else ""


def _resolved(args: argparse.Namespace, saved: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return mode, backend, teammate model, and lead model.

    A plain --resume restores the run provider and models. Explicit arguments
    still let the user start from the saved transcript with different models.
    """
    mode = args.mode or saved.get("mode") or "default"
    backend = "codex" if mode == "gpt6" else "openai" if mode == "gpt6-api" else "claude"
    restore_models = not args.mode or args.mode == saved.get("mode")
    if mode in {"gpt6", "gpt6-api"}:
        model = args.model or (saved.get("model") if restore_models else None) or GPT6_MEMBER_MODEL
        lead_model = args.lead_model or (saved.get("lead_model") if restore_models else None) or GPT6_LEAD_MODEL
    else:
        model = args.model or (saved.get("model") if restore_models else None) or DEFAULT_MODEL
        lead_model = args.lead_model or (saved.get("lead_model") if restore_models else None) or model
    models = (model, lead_model)
    if backend in {"openai", "codex"} and not all(provider.is_openai(value) for value in models):
        raise SystemExit(f"--mode {mode} requires OpenAI model names for --model and --lead-model")
    if backend == "claude" and any(provider.is_openai(value) for value in models):
        raise SystemExit("OpenAI model names require --mode gpt6 or --mode gpt6-api")
    return mode, backend, model, lead_model


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    console = Console(highlight=False)
    roster = load_roster(HOME / "souls")
    runs = HOME / "runs"
    run_dir = current_run(runs) if args.resume else None
    if args.resume and run_dir is None:
        console.print(Text("no previous run to resume; starting a new one", style=theme.BRONZE))
    saved = read_state(run_dir) if run_dir else {}
    mode, backend, model, lead_model = _resolved(args, saved)
    # Validate credentials before creating a run directory or changing CURRENT.
    openai_key = provider.openai_key(REPO) if backend == "openai" else ""
    codex_server = await CodexAppServer.start(REPO) if backend == "codex" else None
    if codex_server is not None:
        try:
            await codex_server.validate([(model, "medium"), (lead_model, "high")], REPO)
        except BaseException:
            await codex_server.close()
            raise
    args.model, args.lead_model = model, lead_model
    deepseek_key = _deepseek_key(args) if backend == "claude" else ""
    run_dir = run_dir or new_run(runs)
    view = ChatView(console, {m.id: m.name for m in roster}, cost_available=backend == "claude")
    log = on_events(EventLog(run_dir), view)
    config = TeamConfig(
        repo=REPO,
        workspace=HOME / "workspace",
        team_rules=(HOME / "TEAM.md").read_text(encoding="utf-8"),
        model=model,
        lead_model=lead_model,
        deepseek_key=deepseek_key,
        backend=backend,
        mode=mode,
        openai_key=openai_key,
        codex_server=codex_server,
    )
    config.workspace.mkdir(exist_ok=True)
    sessions = saved.get("sessions", {})
    # Runs from before provider namespacing stored the Claude IDs directly.
    claude_sessions = sessions.get("claude", {}) if "claude" in sessions else sessions
    swarm = Swarm(roster, config, log, args.turns, claude_sessions, saved.get("openai_histories"),
                  saved.get("codex_threads"))
    swarm._write_state()

    console.print(theme.banner(run_dir.name, len(roster)))
    console.print(Text("  talk to bowling; /help for commands; monitor with: make swarm-monitor\n", style=theme.ASH))
    swarm.start()
    session: PromptSession[str] = PromptSession(
        bottom_toolbar=view.status, refresh_interval=STATUS_REFRESH, style=theme.prompt_style()
    )
    try:
        with patch_stdout(raw=True):
            while True:
                try:
                    line = (await session.prompt_async("you > ")).strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    continue
                if line.startswith("/"):
                    if not await handle_command(line, swarm, console, args.turns):
                        break
                    continue
                swarm.router.send(USER_ID, LEAD_ID, line)
    finally:
        console.print(Text("  shutting down the swarm...", style=theme.ASH))
        await swarm.close()
        total = (f"total ${swarm.total_cost():.2f}" if backend == "claude" else
                 "subscription usage unavailable" if backend == "codex" else
                 "API cost unavailable")
        console.print(Text(f"  run saved in {run_dir}  ({total})", style=theme.ASH))


def run(argv: list[str] | None = None) -> None:
    asyncio.run(main(argv))
