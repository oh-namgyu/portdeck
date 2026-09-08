"""Diagnostics — the checks that turn a registry into an answer.

Every finding names the port, the projects involved, and a one-line fix. Checks
are read-only: portdeck never kills a process or rewrites the registry here.
"""

from __future__ import annotations

import os
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple

from . import live
from .discover import Discovery, scan_project, primary_port
from .registry import Entry, Registry

SEVERITIES = ("high", "medium", "low")
STALE_DAYS = 180


class Finding:
    """One diagnostic result."""

    __slots__ = ("check", "severity", "port", "message", "fix")

    def __init__(self, check: str, severity: str, port: Optional[int],
                 message: str, fix: str = "") -> None:
        self.check = check
        self.severity = severity
        self.port = port
        self.message = message
        self.fix = fix

    def to_dict(self) -> Dict[str, object]:
        return {"check": self.check, "severity": self.severity,
                "port": self.port, "message": self.message, "fix": self.fix}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Finding({}, {}, {})".format(self.check, self.severity, self.port)


def check_collisions(reg: Registry) -> List[Finding]:
    """Two registered projects claiming the same port."""
    out: List[Finding] = []
    for port, group in sorted(reg.by_port().items()):
        if len(group) < 2:
            continue
        names = ", ".join(sorted(e.name for e in group))
        out.append(Finding(
            "collision", "high", port,
            "port {} is claimed by {} projects: {}".format(port, len(group), names),
            "give all but one of them a free port"))
    return out


def check_missing_paths(reg: Registry) -> List[Finding]:
    """Registry entries pointing at a directory that is gone."""
    return [Finding("missing-path", "medium", e.port,
                    "{}: path does not exist ({})".format(e.name, e.path),
                    "fix the path or remove the entry")
            for e in reg.sorted() if e.path and not e.exists()]


def check_drift(reg: Registry, max_source_files: int = 250) -> List[Finding]:
    """Registry port vs. the port the project's own code declares."""
    out: List[Finding] = []
    for e in reg.sorted():
        if not e.exists():
            continue
        hits = scan_project(e.real_path, max_source_files)
        found = primary_port(hits)
        if found is None or found == e.port:
            continue
        ev = next((h for h in hits if h.port == found and not h.incidental), None)
        where = "{}:{}".format(ev.file, ev.line) if ev else "code"
        out.append(Finding(
            "drift", "medium", e.port,
            "{}: registry says {} but code says {} ({})".format(
                e.name, e.port, found, where),
            "update the registry, or the code"))
    return out


def snapshot() -> Tuple[Dict[int, live.Listener], Dict[int, str]]:
    """One look at the machine: who listens where, and from which directory.

    Taken once and passed into the checks so a full report costs two `lsof`
    calls rather than one per port.
    """
    listeners = live.listening_ports()
    return listeners, live.cwds_of(l.pid for l in listeners.values())


def check_squatters(reg: Registry, listeners: Optional[Dict[int, live.Listener]] = None,
                    cwds: Optional[Dict[int, str]] = None) -> List[Finding]:
    """A registered port held by a process running from somewhere else."""
    out: List[Finding] = []
    if listeners is None or cwds is None:
        listeners, cwds = snapshot()
    for e in reg.sorted():
        listener = listeners.get(e.port)
        if not listener or not e.exists():
            continue
        cwd = cwds.get(listener.pid, "")
        if not cwd or _within(cwd, e.real_path):
            continue
        hint = live.system_hint(listener.command, e.port)
        out.append(Finding(
            "squatter", "high", e.port,
            "{} owns port {} but it is held by {} (pid {}) from {}".format(
                e.name, e.port, listener.command or "?", listener.pid, cwd),
            hint or "stop that process or move one of the two"))
    return out


def check_orphans(reg: Registry, listeners: Optional[Dict[int, live.Listener]] = None,
                  cwds: Optional[Dict[int, str]] = None) -> List[Finding]:
    """Listening ports nobody registered."""
    known = set(reg.by_port())
    out: List[Finding] = []
    if listeners is None or cwds is None:
        listeners, cwds = snapshot()
    for port, listener in sorted(listeners.items()):
        if port in known:
            continue
        cwd = cwds.get(listener.pid, "")
        where = " from {}".format(cwd) if cwd else ""
        out.append(Finding(
            "orphan", "low", port,
            "port {} is held by {} (pid {}){} and is not registered".format(
                port, listener.command or "?", listener.pid, where),
            "register it, or leave it alone"))
    return out


def is_running(port: int, listeners: Dict[int, live.Listener]) -> bool:
    """Whether a port is serving, falling back to a probe where lsof is absent."""
    if port in listeners:
        return True
    return not live.has_lsof() and live.is_listening(port)


def check_stale(reg: Registry, listeners: Optional[Dict[int, live.Listener]] = None,
                days: int = STALE_DAYS) -> List[Finding]:
    """Registered projects with no commits for a long time and nothing running."""
    out: List[Finding] = []
    listeners = live.listening_ports() if listeners is None else listeners
    for e in reg.sorted():
        if not e.exists() or is_running(e.port, listeners):
            continue
        age = days_since_commit(e.real_path)
        if age is not None and age >= days:
            out.append(Finding(
                "stale", "low", e.port,
                "{}: no commit in {} days and not running".format(e.name, age),
                "free the port if the project is done"))
    return out


def days_since_commit(path: str) -> Optional[int]:
    """Days since the last git commit, or None outside a repo."""
    try:
        proc = subprocess.run(["git", "log", "-1", "--format=%ct"],
                              capture_output=True, text=True, timeout=5, cwd=path)
    except (OSError, subprocess.SubprocessError):
        return None
    stamp = proc.stdout.strip()
    if not stamp.isdigit():
        return None
    import time
    return max(0, int((time.time() - int(stamp)) // 86400))


def check_unregistered(reg: Registry, discoveries: Sequence[Discovery]) -> List[Finding]:
    """Scanned projects with a port that the registry does not know about."""
    known_paths = {e.real_path for e in reg.entries if e.real_path}
    out: List[Finding] = []
    for d in discoveries:
        if d.port is None or d.root in known_paths:
            continue
        out.append(Finding(
            "unregistered", "low", d.port,
            "{}: uses port {} but is not in the registry".format(d.name, d.port),
            "portdeck scan --write"))
    return out


def _within(child: str, parent: str) -> bool:
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def run(reg: Registry, discoveries: Optional[Sequence[Discovery]] = None,
        include_stale: bool = False) -> List[Finding]:
    """Run every check and return findings sorted by severity."""
    listeners, cwds = snapshot()
    findings = (check_collisions(reg) + check_squatters(reg, listeners, cwds)
                + check_missing_paths(reg) + check_drift(reg)
                + check_orphans(reg, listeners, cwds))
    if discoveries:
        findings += check_unregistered(reg, discoveries)
    if include_stale:
        findings += check_stale(reg, listeners)
    return sorted(findings, key=lambda f: (SEVERITIES.index(f.severity),
                                           f.port or 0, f.check))


def entry_status(entry: Entry, listeners: Dict[int, live.Listener],
                 cwds: Optional[Dict[int, str]] = None) -> Dict[str, object]:
    """Live status of one registry entry, for `portdeck ls`."""
    listener = listeners.get(entry.port)
    owned = True
    if listener and entry.exists():
        cwd = (cwds or {}).get(listener.pid) or live.cwd_of(listener.pid)
        owned = not cwd or _within(cwd, entry.real_path)
    return {"name": entry.name, "port": entry.port, "path": entry.path,
            "running": is_running(entry.port, listeners),
            "pid": listener.pid if listener else None,
            "command": listener.command if listener else "",
            "owned": owned}
