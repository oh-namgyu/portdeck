"""Watch mode — report ports as they come up and go down.

The comparison is a pure function so the behaviour is testable without waiting
on real sockets; only `run` sleeps.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from . import live, render
from .registry import Registry

DEFAULT_INTERVAL = 2.0


class Event:
    """A port that started or stopped listening."""

    __slots__ = ("kind", "port", "project", "command", "pid")

    def __init__(self, kind: str, port: int, project: str = "",
                 command: str = "", pid: int = 0) -> None:
        self.kind = kind
        self.port = port
        self.project = project
        self.command = command
        self.pid = pid

    def to_dict(self) -> Dict[str, object]:
        return {"kind": self.kind, "port": self.port, "project": self.project,
                "command": self.command, "pid": self.pid}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Event({}, {}, {!r})".format(self.kind, self.port, self.project)


def diff(before: Dict[int, live.Listener], after: Dict[int, live.Listener],
         names: Optional[Dict[int, str]] = None) -> List[Event]:
    """Ports that appeared, disappeared, or changed owner between two looks."""
    names = names or {}
    events: List[Event] = []
    for port in sorted(set(before) | set(after)):
        old, new = before.get(port), after.get(port)
        name = names.get(port, "")
        if new and not old:
            events.append(Event("up", port, name, new.command, new.pid))
        elif old and not new:
            events.append(Event("down", port, name, old.command, old.pid))
        elif old and new and old.pid != new.pid:
            events.append(Event("replaced", port, name, new.command, new.pid))
    return events


def format_event(event: Event) -> str:
    """One line per event, coloured by direction."""
    mark, color = {"up": ("+", "green"), "down": ("-", "dim")}.get(
        event.kind, ("~", "yellow"))
    who = "{} ({})".format(event.command, event.pid) if event.command else ""
    label = event.project or "unregistered"
    return "{} {:>5}  {}  {}".format(
        render.paint(mark, color), event.port, label, render.paint(who, "dim")).rstrip()


def run(reg: Registry, interval: float = DEFAULT_INTERVAL,
        emit: Optional[Callable[[Event], None]] = None,
        rounds: Optional[int] = None) -> int:
    """Poll until interrupted, printing each change.

    `rounds` bounds the loop for tests; None means "until Ctrl-C".
    """
    emit = emit or (lambda e: print(format_event(e)))
    names = reg.port_names()
    previous = live.listening_ports()
    print(render.paint("watching {} ports — Ctrl-C to stop".format(len(previous)), "dim"))
    count = 0
    try:
        while rounds is None or count < rounds:
            time.sleep(interval)
            current = live.listening_ports()
            for event in diff(previous, current, names):
                emit(event)
            previous = current
            count += 1
    except KeyboardInterrupt:
        print()
    return 0
