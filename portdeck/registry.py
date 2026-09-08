"""Registry storage — the list of local projects and the ports they own.

The registry is a plain JSON file so it can be hand-edited or committed to a
team repo. Two shapes are accepted on load (a bare list is the common shape of
hand-rolled `ports.json` files):

    {"version": 1, "projects": [{"name": ..., "port": ..., "path": ...}]}
    [{"name": ..., "port": ..., "path": ...}]

Writes always use the object shape.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

VERSION = 1
ENV_VAR = "PORTDECK_REGISTRY"
LOCAL_NAME = "portdeck.json"


class Entry:
    """One registered project."""

    __slots__ = ("name", "port", "path", "note", "source")

    def __init__(self, name: str, port: int, path: str = "",
                 note: str = "", source: str = "manual") -> None:
        self.name = name
        self.port = int(port)
        self.path = path
        self.note = note
        self.source = source

    @property
    def real_path(self) -> str:
        """Absolute, symlink-resolved project path ('' when unset)."""
        if not self.path:
            return ""
        return os.path.realpath(os.path.expanduser(self.path))

    def exists(self) -> bool:
        return bool(self.real_path) and os.path.isdir(self.real_path)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "port": self.port, "path": self.path}
        if self.note:
            out["note"] = self.note
        if self.source and self.source != "manual":
            out["source"] = self.source
        return out

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> Optional["Entry"]:
        """Build an entry, or None when the record is unusable.

        A single broken record must never take down the whole registry.
        """
        try:
            name = str(raw.get("name") or "").strip()
            port = int(raw.get("port"))
        except (TypeError, ValueError):
            return None
        if not name or not (0 < port < 65536):
            return None
        return cls(name, port, str(raw.get("path") or ""),
                   str(raw.get("note") or ""), str(raw.get("source") or "manual"))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Entry({!r}, {}, {!r})".format(self.name, self.port, self.path)


def tilde_path(path: str) -> str:
    """Store paths under $HOME as ~/... so a registry can be shared."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def default_path(cwd: Optional[str] = None) -> str:
    """Resolve the registry location: env var, then ./portdeck.json, then XDG."""
    env = os.environ.get(ENV_VAR)
    if env:
        return os.path.expanduser(env)
    local = os.path.join(cwd or os.getcwd(), LOCAL_NAME)
    if os.path.isfile(local):
        return local
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "portdeck", "registry.json")


class Registry:
    """A loaded registry plus the path it came from."""

    def __init__(self, entries: Iterable[Entry], path: str) -> None:
        self.entries: List[Entry] = list(entries)
        self.path = path

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Registry":
        path = path or default_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return cls([], path)
        records = raw.get("projects", []) if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            return cls([], path)
        entries = [Entry.from_dict(r) for r in records if isinstance(r, dict)]
        return cls([e for e in entries if e], path)

    def save(self, path: Optional[str] = None) -> str:
        target = path or self.path
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {"version": VERSION,
                   "projects": [e.to_dict() for e in self.sorted()]}
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, target)
        return target

    def sorted(self) -> List[Entry]:
        return sorted(self.entries, key=lambda e: (e.port, e.name))

    def by_port(self) -> Dict[int, List[Entry]]:
        """port -> entries. A list because collisions are exactly what we hunt."""
        out: Dict[int, List[Entry]] = {}
        for e in self.entries:
            out.setdefault(e.port, []).append(e)
        return out

    def port_names(self) -> Dict[int, str]:
        """port -> first registered name, for resolving outbound calls."""
        return {port: group[0].name for port, group in self.by_port().items()}

    def find(self, needle: str) -> Optional[Entry]:
        """Look an entry up by name, port, or project path."""
        needle = needle.strip()
        for e in self.entries:
            if e.name == needle:
                return e
        if needle.isdigit():
            for e in self.entries:
                if e.port == int(needle):
                    return e
        real = os.path.realpath(os.path.expanduser(needle))
        for e in self.entries:
            if e.real_path and e.real_path == real:
                return e
        lowered = needle.lower()
        matches = [e for e in self.entries if lowered in e.name.lower()]
        return matches[0] if len(matches) == 1 else None

    def upsert(self, entry: Entry) -> str:
        """Add or update by project path (falling back to name). Returns the action."""
        for i, e in enumerate(self.entries):
            same_path = bool(e.real_path) and e.real_path == entry.real_path
            if same_path or e.name == entry.name:
                if e.port == entry.port and e.path == entry.path:
                    return "unchanged"
                self.entries[i] = entry
                return "updated"
        self.entries.append(entry)
        return "added"
