"""Port discovery — read a project and work out which port it wants.

Nothing is executed and nothing is guessed from a running process: every hit is
a literal found in a file, carried with the file and line that produced it so a
wrong answer can be argued with.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .paths import SOURCE_EXTS, iter_files, read_text

# Evidence kinds, strongest first — a container mapping or an explicit listen
# call beats a default that an environment variable can override.
KIND_ORDER = ("compose", "listen", "config", "script", "env", "const")

ENV_FILES = (".env", ".env.example", ".env.local", ".env.sample", ".env.defaults")
CONFIG_FILES = ("package.json", "Procfile", "Makefile", "docker-compose.yml",
                "docker-compose.yaml", "compose.yml", "compose.yaml")
JSON_CONFIG_FILES = ("config.json", "app.json", "server.json", "settings.json")
MAX_SOURCE_FILES = 600

RE_ENV_ASSIGN = re.compile(
    r"^\s*(?:export\s+)?[A-Z0-9_]*PORT[A-Z0-9_]*\s*[:=]\s*[\"']?(\d{2,5})\b")
# Module-level constants: `PORT = 5030`, `PORT: int = 6040`, `const PORT = 3000`,
# `PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 6140`. The right-hand side is
# captured whole and the first plausible number in it wins.
RE_CONST_ASSIGN = re.compile(
    r"^\s*(?:(?:export\s+)?(?:const|let|var)\s+)?"
    r"[A-Za-z0-9_]*PORT[A-Za-z0-9_]*\s*(?::\s*[\w\[\]., ]+?\s*)?=\s*(.+)$")
RE_NUMBER = re.compile(r"\b(\d{2,5})\b")
RE_LISTEN_CALL = re.compile(r"\.listen\(\s*[\"']?(\d{2,5})\b")
RE_RUN_KWARG = re.compile(r"\bport\s*=\s*[\"']?(\d{2,5})\b")
RE_ENV_FALLBACK = re.compile(
    r"(?:process\.env\.[A-Z0-9_]*PORT[A-Z0-9_]*\s*\|\|\s*|"
    r"environ(?:\.get)?\(\s*[\"'][A-Z0-9_]*PORT[A-Z0-9_]*[\"']\s*,\s*)[\"']?(\d{2,5})\b")
RE_CLI_PORT = re.compile(r"(?:--port[=\s]+|(?<![\w-])-p\s+)[\"']?(\d{2,5})\b")
# Static servers take the port as a bare argument: `python3 -m http.server 6060`.
RE_SERVER_CMD = re.compile(r"(?:http\.server|http-server|serve|py -m SimpleHTTPServer)\s+(\d{2,5})\b")
RE_COMPOSE_MAP = re.compile(r"^\s*-\s*[\"']?(?:[\d.]+:)?(\d{2,5}):\d{2,5}")
RE_RUN_CONTEXT = re.compile(r"\b(?:run|serve|listen|Server|createServer|bind)\s*\(")


# Tests, examples and verification harnesses spin up throwaway servers; their
# ports are real literals but never the project's own.
INCIDENTAL_DIRS = {"test", "tests", "spec", "specs", "__tests__", "e2e",
                   "examples", "example", "fixtures", "benchmarks", "demo"}
INCIDENTAL_PREFIXES = ("test_", "verify_", "bench_", "demo_", "example_")
INCIDENTAL_SUFFIXES = ("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts")


def is_incidental(rel: str) -> bool:
    """True when a path is a test/example harness rather than the app itself."""
    parts = rel.replace("\\", "/").split("/")
    if any(p.lower() in INCIDENTAL_DIRS for p in parts[:-1]):
        return True
    base = parts[-1].lower()
    return base.startswith(INCIDENTAL_PREFIXES) or base.endswith(INCIDENTAL_SUFFIXES)


class PortHit:
    """One piece of evidence that a project uses a port."""

    __slots__ = ("port", "kind", "file", "line", "snippet", "incidental")

    def __init__(self, port: int, kind: str, file: str, line: int, snippet: str) -> None:
        self.port = port
        self.kind = kind
        self.file = file
        self.line = line
        self.snippet = snippet.strip()[:120]
        self.incidental = is_incidental(file)

    @property
    def rank(self) -> int:
        return KIND_ORDER.index(self.kind) if self.kind in KIND_ORDER else len(KIND_ORDER)

    def to_dict(self) -> Dict[str, object]:
        return {"port": self.port, "kind": self.kind, "file": self.file,
                "line": self.line, "snippet": self.snippet}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "PortHit({}, {}, {}:{})".format(self.port, self.kind, self.file, self.line)


COMMENT_MARKERS = ("#", "//", "*", '"""', "'''", "<!--", ";")


def is_comment(line: str) -> bool:
    """A commented-out port is not a declaration."""
    return line.lstrip().startswith(COMMENT_MARKERS)


def plausible(port: int) -> bool:
    """Filter out numbers that are syntactically ports but never used as one."""
    return port in (80, 443) or 1024 <= port <= 65535


def _scan_lines(text: str, rel: str, klass: str) -> List[PortHit]:
    """Apply the line patterns to one file's text.

    `klass` is the role of the file — "env", "script", "source" or "compose" —
    which decides how an assignment is labelled.
    """
    hits: List[PortHit] = []
    if "compose" in os.path.basename(rel):
        klass = "compose"
    for no, line in enumerate(text.splitlines(), 1):
        if len(line) > 400 or is_comment(line):
            continue
        for port, kind in _line_hits(line, klass):
            if plausible(port):
                hits.append(PortHit(port, kind, rel, no, line))
    return hits


def _line_hits(line: str, klass: str) -> Iterable[Tuple[int, str]]:
    """Yield (port, kind) for one line of text."""
    if klass == "compose":
        m = RE_COMPOSE_MAP.search(line)
        if m:
            yield int(m.group(1)), "compose"
        return
    for m in RE_LISTEN_CALL.finditer(line):
        yield int(m.group(1)), "listen"
    if RE_RUN_CONTEXT.search(line):
        for m in RE_RUN_KWARG.finditer(line):
            yield int(m.group(1)), "listen"
    for m in RE_ENV_FALLBACK.finditer(line):
        yield int(m.group(1)), "const"
    # A command line inside source code usually starts *another* service, so it
    # only counts as a weak signal; in a real script file it is the start command.
    cmd_kind = "script" if klass == "script" else "const"
    for m in RE_CLI_PORT.finditer(line):
        yield int(m.group(1)), cmd_kind
    for m in RE_SERVER_CMD.finditer(line):
        yield int(m.group(1)), cmd_kind
    for port in _assignment_ports(line, klass):
        yield port, {"env": "env", "script": "script"}.get(klass, "const")


def _assignment_ports(line: str, klass: str) -> Iterable[int]:
    """Ports from a `*PORT* = ...` assignment."""
    m = RE_ENV_ASSIGN.search(line)
    if m:
        yield int(m.group(1))
        return
    if klass in ("env", "script"):
        return
    m = RE_CONST_ASSIGN.match(line)
    if not m:
        return
    for num in RE_NUMBER.findall(m.group(1)):
        if plausible(int(num)):
            yield int(num)
            return


def _scan_package_json(root: str) -> List[PortHit]:
    """Ports named in npm scripts (`next dev -p 3000`, `vite --port 5173`)."""
    path = os.path.join(root, "package.json")
    text = read_text(path)
    if not text:
        return []
    try:
        scripts = (json.loads(text).get("scripts") or {})
    except (ValueError, AttributeError):
        return []
    hits: List[PortHit] = []
    for name, command in scripts.items():
        if not isinstance(command, str):
            continue
        for port, _kind in _line_hits(command, "script"):
            if plausible(port):
                hits.append(PortHit(port, "script", "package.json", 0,
                                    "{}: {}".format(name, command)))
    return hits


def _scan_json_config(root: str, name: str) -> List[PortHit]:
    """Ports declared as a `"port": N` key in a JSON config file."""
    text = read_text(os.path.join(root, name))
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    hits: List[PortHit] = []
    for holder in _json_dicts(data, depth=2):
        for key, value in holder.items():
            if "port" not in key.lower() or not isinstance(value, int):
                continue
            if plausible(value):
                hits.append(PortHit(value, "config", name, 0,
                                    '"{}": {}'.format(key, value)))
    return hits


def _json_dicts(node: object, depth: int) -> Iterable[Dict[str, object]]:
    """Yield dicts from a decoded JSON tree, down to `depth` levels."""
    if isinstance(node, dict):
        yield node
        if depth > 0:
            for value in node.values():
                for sub in _json_dicts(value, depth - 1):
                    yield sub


def scan_project(root: str, max_source_files: int = MAX_SOURCE_FILES) -> List[PortHit]:
    """All port evidence for one project, best evidence first."""
    hits: List[PortHit] = []
    for name in ENV_FILES:
        text = read_text(os.path.join(root, name))
        if text:
            hits += _scan_lines(text, name, "env")
    for name in CONFIG_FILES:
        if name == "package.json":
            hits += _scan_package_json(root)
            continue
        text = read_text(os.path.join(root, name))
        if text:
            hits += _scan_lines(text, name, "script")
    for name in JSON_CONFIG_FILES:
        hits += _scan_json_config(root, name)
    for full, rel, _ext in iter_files(root, SOURCE_EXTS, max_source_files):
        text = read_text(full)
        if text:
            hits += _scan_lines(text, rel, "source")
    return _dedupe(hits)


def _dedupe(hits: Sequence[PortHit]) -> List[PortHit]:
    seen = set()
    out: List[PortHit] = []
    for h in sorted(hits, key=lambda x: (x.rank, x.port, x.file, x.line)):
        key = (h.port, h.kind, h.file, h.line)
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def primary_port(hits: Sequence[PortHit]) -> Optional[int]:
    """Pick the port a project most likely serves on.

    Strongest evidence kind wins; within a kind, the most-cited port wins, and
    ties break toward the lower port number for stability.
    """
    pool = [h for h in hits if not h.incidental] or list(hits)
    if not pool:
        return None
    best_rank = min(h.rank for h in pool)
    counts: Dict[int, int] = {}
    for h in pool:
        if h.rank == best_rank:
            counts[h.port] = counts.get(h.port, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


class Discovery:
    """A discovered project: its root, chosen port, and the evidence behind it."""

    __slots__ = ("root", "name", "port", "hits")

    def __init__(self, root: str, hits: Sequence[PortHit]) -> None:
        self.root = root
        self.name = os.path.basename(root.rstrip(os.sep))
        self.hits = list(hits)
        self.port = primary_port(self.hits)

    @property
    def evidence(self) -> List[PortHit]:
        """Hits that back the chosen port, real code before test harnesses."""
        same = [h for h in self.hits if h.port == self.port]
        return [h for h in same if not h.incidental] or same

    @property
    def source(self) -> str:
        ev = self.evidence
        return "scan:{}".format(ev[0].kind) if ev else "scan"

    def to_dict(self) -> Dict[str, object]:
        return {"name": self.name, "port": self.port, "path": self.root,
                "evidence": [h.to_dict() for h in self.evidence[:5]]}


def discover(roots: Sequence[str], depth: int = 2,
             max_source_files: int = MAX_SOURCE_FILES) -> List[Discovery]:
    """Find projects under roots and resolve each one's port."""
    from .paths import find_projects  # local import keeps the module import light

    out: List[Discovery] = []
    for root in find_projects(roots, depth):
        out.append(Discovery(root, scan_project(root, max_source_files)))
    return out
