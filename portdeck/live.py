"""Live socket state — what is actually listening right now.

Two independent signals are used, because they answer different questions:

* a TCP connect tells us the port is *serving* (works without privileges),
* `lsof` tells us *who* owns it (pid/command), which is what makes drift and
  orphan findings actionable.

`lsof` is optional: everything degrades to the connect probe when it is absent
(non-macOS/Linux hosts, restricted environments).
"""

from __future__ import annotations

import functools
import os
import shutil
import socket
import subprocess
from typing import Dict, Iterable, List, Optional

CONNECT_TIMEOUT = 0.25
LSOF_TIMEOUT = 5.0


class Listener:
    """The process holding a port."""

    __slots__ = ("port", "pid", "command", "user")

    def __init__(self, port: int, pid: int, command: str, user: str = "") -> None:
        self.port = port
        self.pid = pid
        self.command = command
        self.user = user

    def to_dict(self) -> Dict[str, object]:
        return {"port": self.port, "pid": self.pid,
                "command": self.command, "user": self.user}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Listener({}, pid={}, {!r})".format(self.port, self.pid, self.command)


def is_listening(port: int, host: str = "127.0.0.1",
                 timeout: float = CONNECT_TIMEOUT) -> bool:
    """True when something accepts a TCP connection on the port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def has_lsof() -> bool:
    return _lsof_binary() is not None


@functools.lru_cache(maxsize=1)
def _lsof_binary() -> Optional[str]:
    """Find lsof, including macOS's /usr/sbin copy that is often off PATH."""
    found = shutil.which("lsof")
    if found:
        return found
    for path in ("/usr/sbin/lsof", "/usr/bin/lsof"):
        if os.access(path, os.X_OK):
            return path
    return None


def _run_lsof(args: List[str]) -> str:
    binary = _lsof_binary()
    if not binary:
        return ""
    try:
        proc = subprocess.run([binary] + args, capture_output=True, text=True,
                              timeout=LSOF_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    # lsof exits 1 when nothing matches; that is a normal empty result.
    return proc.stdout or ""


def _parse_field_output(text: str) -> Dict[int, Listener]:
    """Parse `lsof -F pcnLu` records into port -> Listener.

    Field output is one `<tag><value>` per line; process fields (p/c/L/u) apply
    to every following file record until the next process block.
    """
    listeners: Dict[int, Listener] = {}
    pid, command, user = 0, "", ""
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            pid = int(value) if value.isdigit() else 0
            command, user = "", ""
        elif tag == "c":
            command = value
        elif tag in ("L", "u"):
            user = user or value
        elif tag == "n":
            port = _port_from_name(value)
            if port and port not in listeners:
                listeners[port] = Listener(port, pid, command, user)
    return listeners


def _port_from_name(name: str) -> Optional[int]:
    """Extract the local port from an lsof name field ('*:4400', '[::1]:80')."""
    local = name.split("->", 1)[0].strip()
    if ":" not in local:
        return None
    tail = local.rsplit(":", 1)[1]
    return int(tail) if tail.isdigit() else None


def listening_ports() -> Dict[int, Listener]:
    """Every TCP port in LISTEN state on this host, keyed by port."""
    return _parse_field_output(_run_lsof(["-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pcnu"]))


# Ports that a well-known system service quietly takes over. Knowing this is the
# difference between "my server is broken" and "turn off AirPlay Receiver".
SYSTEM_HOLDERS = {
    ("ControlCenter", 5000): "macOS AirPlay Receiver — System Settings → General "
                             "→ AirDrop & Handoff",
    ("ControlCenter", 7000): "macOS AirPlay Receiver — System Settings → General "
                             "→ AirDrop & Handoff",
    ("rapportd", 49152): "macOS Continuity (Rapport)",
}


def system_hint(command: str, port: int) -> str:
    """Explanation for a port held by a known system service ('' otherwise)."""
    return SYSTEM_HOLDERS.get((command, port), "")


def cwds_of(pids: Iterable[int]) -> Dict[int, str]:
    """Working directory per pid, in one lsof call.

    This is what turns "something is on 6040" into "the *wrong* thing is on
    6040": compare it against the registered project path.
    """
    wanted = [p for p in dict.fromkeys(pids) if p > 0]
    if not wanted:
        return {}
    text = _run_lsof(["-p", ",".join(str(p) for p in wanted), "-a", "-d", "cwd", "-F", "n"])
    out: Dict[int, str] = {}
    current = 0
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            current = int(line[1:])
        elif line.startswith("n/") and current:
            out.setdefault(current, line[1:])
    return out


def cwd_of(pid: int) -> str:
    """Working directory of one process ('' when unknown)."""
    return cwds_of([pid]).get(pid, "")


def owner_of(port: int) -> Optional[Listener]:
    """The process listening on one port, or None."""
    found = _parse_field_output(
        _run_lsof(["-nP", "-iTCP:{}".format(port), "-sTCP:LISTEN", "-F", "pcnu"]))
    return found.get(port) or (next(iter(found.values())) if found else None)
