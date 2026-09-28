"""What the monitor knows, rebuilt from events. Pure: apply(state, event) -> new state."""

from __future__ import annotations

import dataclasses
from typing import Any

TRAFFIC_KEEP = 40
ACTIVITY_KEEP = 60


@dataclasses.dataclass(frozen=True)
class AgentView:
    id: str
    name: str
    role: str
    lead: bool = False
    state: str = "idle"     # idle | working | error
    since: float = 0.0      # when the current state began
    last: str = ""          # latest tool call or remark
    last_at: float = 0.0    # when `last` happened
    turns: int = 0
    cost: float = 0.0


@dataclasses.dataclass(frozen=True)
class Line:
    ts: float
    who: str
    to: str
    text: str
    kind: str  # message | user | reply | tool | text | notice | error


@dataclasses.dataclass(frozen=True)
class MonitorState:
    run: str = ""
    started: float = 0.0
    model: str = ""
    backend: str = "claude"
    agents: tuple[AgentView, ...] = ()
    traffic: tuple[Line, ...] = ()
    activity: tuple[Line, ...] = ()
    turns_left: int | None = None

    def total_cost(self) -> float:
        return sum(a.cost for a in self.agents)

    def working(self) -> int:
        return sum(a.state == "working" for a in self.agents)


def _with_agent(board: MonitorState, agent_id: str, **changes: Any) -> MonitorState:
    agents = tuple(dataclasses.replace(a, **changes) if a.id == agent_id else a for a in board.agents)
    return dataclasses.replace(board, agents=agents)


def _agent(state: MonitorState, agent_id: str) -> AgentView | None:
    return next((a for a in state.agents if a.id == agent_id), None)


def _push(lines: tuple[Line, ...], line: Line, keep: int) -> tuple[Line, ...]:
    return (lines + (line,))[-keep:]


def apply(state: MonitorState, event: dict[str, Any]) -> MonitorState:
    kind, ts = event.get("type"), event.get("ts", 0.0)
    agent_id = event.get("agent", "")

    if kind == "run_start":
        agents = tuple(AgentView(m["id"], m["name"], m["role"], m.get("lead", False)) for m in event["members"])
        return dataclasses.replace(state, started=state.started or ts, agents=agents,
                                   turns_left=event.get("budget"), model=event.get("model", ""),
                                   backend=event.get("backend", "claude"))

    if kind in ("message", "user"):
        line = Line(ts, event["sender"], event["to"], event["text"], kind)
        return dataclasses.replace(state, traffic=_push(state.traffic, line, TRAFFIC_KEEP))

    if kind == "reply":
        line = Line(ts, agent_id, "user", event["text"], kind)
        return dataclasses.replace(state, traffic=_push(state.traffic, line, TRAFFIC_KEEP))

    if kind in ("tool", "text"):
        text = f"{event['name']}  {event['summary']}" if kind == "tool" else event["text"].split("\n", 1)[0]
        new = _with_agent(state, agent_id, last=text, last_at=ts)
        return dataclasses.replace(new, activity=_push(new.activity, Line(ts, agent_id, "", text, kind),
                                                       ACTIVITY_KEEP))

    if kind == "state":
        new = _with_agent(state, agent_id, state=event["state"], since=ts)
        if "turns_left" in event:
            new = dataclasses.replace(new, turns_left=event["turns_left"])
        return new

    if kind == "turn_end":
        current = _agent(state, agent_id)
        if current is None:
            return state
        return _with_agent(state, agent_id, turns=current.turns + 1, cost=current.cost + event.get("cost_usd", 0.0))

    if kind in ("notice", "error"):
        new = state
        if "turns_left" in event:
            new = dataclasses.replace(new, turns_left=event["turns_left"])
        if kind == "error" and agent_id:
            new = _with_agent(new, agent_id, state="error", since=ts, last=event["text"])
        line = Line(ts, agent_id or "swarm", "", event["text"], kind)
        return dataclasses.replace(new, activity=_push(new.activity, line, ACTIVITY_KEEP))

    return state
