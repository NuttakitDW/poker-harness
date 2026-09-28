"""The Monitor terminal: a live board of the swarm, drawn from the current run's events.

Read-only. It follows runs/CURRENT, so start it before or after the chat;
when a new chat run begins it switches over by itself.
    swarm monitor            follow the live run
    swarm monitor <run-dir>  replay a finished run
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from swarm import theme
from swarm.events import EVENTS, current_run, read_new
from swarm.monitor_state import AgentView, Line, MonitorState, apply

HOME = Path(__file__).resolve().parents[1]
POLL_SECONDS = 0.25

STATE_STYLE = {"working": f"bold {theme.SIGNAL}", "idle": theme.ASH, "error": theme.ERROR}
LINE_STYLE = {"notice": theme.BRONZE, "error": theme.ERROR, "text": theme.PALE, "tool": theme.ASH}


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def stamp(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def header(state: MonitorState, now: float) -> Text:
    turns = "-" if state.turns_left is None else str(state.turns_left)
    cost = f"${state.total_cost():.2f}" if state.backend == "claude" else "unavailable"
    return Text.assemble(
        (" DEEPSTACK", f"bold {theme.PALE}"), (" / ", theme.ASH), ("SWARM", f"bold {theme.SIGNAL}"),
        (f"   run {state.run or 'waiting'}", theme.BRONZE),
        ("   elapsed ", theme.ASH), (clock(now - state.started) if state.started else "-", theme.PALE),
        ("   working ", theme.ASH), (f"{state.working()}/{len(state.agents)}", theme.SIGNAL),
        ("   turns left ", theme.ASH), (turns, theme.SIGNAL if state.turns_left else theme.ERROR),
        ("   cost ", theme.ASH), (cost, theme.PALE),
        (f"   {state.model}", theme.ASH),
    )


def agent_row(agent: AgentView, now: float, cost_available: bool = True) -> list[Text]:
    status = agent.state.upper()
    if agent.state == "working":
        status += f" {int(now - agent.since)}s"
    name_style = theme.LEAD if agent.lead else theme.PALE
    return [
        Text(agent.id, style=theme.SIGNAL if agent.lead else theme.BRONZE),
        Text(agent.name, style=name_style),
        Text(agent.role, style=theme.ASH, overflow="ellipsis", no_wrap=True),
        Text(status, style=STATE_STYLE.get(agent.state, theme.ASH)),
        Text(str(agent.turns), style=theme.PALE, justify="right"),
        Text(f"${agent.cost:.2f}" if cost_available else "—", style=theme.PALE, justify="right"),
        Text(agent.last, style=theme.ASH, overflow="ellipsis", no_wrap=True),
    ]


def agents_table(state: MonitorState, now: float) -> Table:
    table = Table(box=box.SIMPLE_HEAD, expand=True, header_style=theme.BRONZE, border_style=theme.EDGE,
                  pad_edge=False)
    table.add_column("id", width=9, no_wrap=True)
    table.add_column("persona", width=18, no_wrap=True)
    table.add_column("role", ratio=2, no_wrap=True)
    table.add_column("state", width=12, no_wrap=True)
    table.add_column("turns", width=5, justify="right")
    table.add_column("cost", width=7, justify="right")
    table.add_column("latest", ratio=3, no_wrap=True)
    for agent in state.agents:
        table.add_row(*agent_row(agent, now, state.backend == "claude"))
    return table


def traffic_line(line: Line) -> Group:
    """Two lines per message: who to whom, then the text cut to one line."""
    who_style = theme.SIGNAL if line.who in ("bowling", "user") else theme.BRONZE
    head = Text.assemble(
        (f"{stamp(line.ts)} ", theme.ASH), (line.who, who_style), (" -> ", theme.ASH),
        (line.to, theme.SIGNAL if line.to in ("bowling", "user") else theme.BRONZE),
    )
    body = Text("  " + " ".join(line.text.split()), style=theme.PALE, no_wrap=True, overflow="ellipsis")
    return Group(head, body)


def activity_line(line: Line) -> Text:
    return Text.assemble(
        (f"{stamp(line.ts)} ", theme.ASH), (f"{line.who:9} ", theme.BRONZE),
        (" ".join(line.text.split()), LINE_STYLE.get(line.kind, theme.ASH)),
        no_wrap=True, overflow="ellipsis",
    )


def tail(lines: tuple[Line, ...], render, height: int, per_line: int) -> Group:
    """The newest lines that fit, oldest on top."""
    count = max(1, height // per_line)
    return Group(*(render(line) for line in lines[-count:]))


def board(state: MonitorState, console: Console) -> Layout:
    now = time.time()
    height = console.size.height
    layout = Layout()
    layout.split_column(
        Layout(Panel(header(state, now), border_style=theme.EDGE, box=box.HORIZONTALS), size=3, name="head"),
        Layout(Panel(agents_table(state, now), title=Text(" team ", style=theme.BRONZE), title_align="left",
                     border_style=theme.EDGE), size=len(state.agents) + 5, name="team"),
        Layout(name="feeds"),
    )
    feed_height = max(4, height - len(state.agents) - 10)
    layout["feeds"].split_row(
        Layout(Panel(tail(state.traffic, traffic_line, feed_height, 2), title=Text(" messages ", style=theme.BRONZE),
                     title_align="left", border_style=theme.EDGE), ratio=5),
        Layout(Panel(tail(state.activity, activity_line, feed_height, 1), title=Text(" activity ", style=theme.BRONZE),
                     title_align="left", border_style=theme.EDGE), ratio=6),
    )
    return layout


def follow(runs_dir: Path, fixed: Path | None) -> None:
    console = Console(highlight=False)
    state, run_dir, offset = MonitorState(), None, 0
    with Live(board(state, console), console=console, screen=True, auto_refresh=False) as live:
        while True:
            target = fixed or current_run(runs_dir)
            if target != run_dir:
                state, run_dir, offset = MonitorState(run=target.name if target else ""), target, 0
            if run_dir is not None:
                events, offset = read_new(run_dir / EVENTS, offset)
                for event in events:
                    state = apply(state, event)
            live.update(board(state, console), refresh=True)
            time.sleep(POLL_SECONDS)


def run(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="swarm monitor", description="Watch the DeepStack swarm work.")
    p.add_argument("run_dir", nargs="?", type=Path, help="a finished run to replay (default: follow the live run)")
    args = p.parse_args(argv)
    try:
        follow(HOME / "runs", args.run_dir.resolve() if args.run_dir else None)
    except KeyboardInterrupt:
        pass
