"""Static topology — what a project exposes and what it calls.

Endpoints and outbound calls are read out of the source with regexes; no import,
no execution. Outbound `host:port` targets are resolved against the registry, so
a local call stops being a URL and becomes an edge between two of your projects.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from .paths import SOURCE_EXTS, iter_files, is_skipped, read_text
from .registry import Registry

FLASK_ROUTE_RE = re.compile(r"@(\w+)\.route\(\s*['\"]([^'\"]+)['\"]([^)]*)\)")
FLASK_VERB_RE = re.compile(r"@(\w+)\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]+)['\"]")
METHODS_RE = re.compile(r"methods\s*=\s*\[([^\]]*)\]")
EXPRESS_RE = re.compile(
    r"\b(?:app|router|r|server)\.(get|post|put|delete|patch|all)\(\s*['\"]([^'\"]+)['\"]")
FASTAPI_RE = re.compile(r"@(\w+)\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]+)['\"]")
NEXT_METHOD_RE = re.compile(
    r"export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b")
URL_RE = re.compile(r"https?://([\w.\-]+):(\d{2,5})(/[\w./\-:{}$]*)?")

ENTRYPOINT_NAMES = {
    "app.py": "python", "main.py": "python", "manage.py": "django",
    "wsgi.py": "wsgi", "asgi.py": "asgi", "server.py": "python",
    "server.js": "node", "index.js": "node", "app.js": "node",
    "main.js": "node", "main.go": "go",
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}


def _flask_endpoints(text: str, rel: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for m in FLASK_ROUTE_RE.finditer(text):
        path, tail = m.group(2), m.group(3) or ""
        found = METHODS_RE.search(tail)
        methods = ([x.strip().strip("'\"").upper() for x in found.group(1).split(",")]
                   if found else ["GET"])
        for method in [x for x in methods if x]:
            out.append({"method": method, "path": path, "file": rel})
    for m in FASTAPI_RE.finditer(text):
        out.append({"method": m.group(2).upper(), "path": m.group(3), "file": rel})
    for m in FLASK_VERB_RE.finditer(text):
        out.append({"method": m.group(2).upper(), "path": m.group(3), "file": rel})
    return out


def _express_endpoints(text: str, rel: str) -> List[Dict[str, str]]:
    return [{"method": m.group(1).upper(), "path": m.group(2), "file": rel}
            for m in EXPRESS_RE.finditer(text)]


def _next_path(segments: Sequence[str]) -> str:
    kept = [s for s in segments if not (s.startswith("(") and s.endswith(")"))]
    return "/" + "/".join(kept) if kept else "/"


def _next_endpoints(rel: str, text: str) -> List[Dict[str, str]]:
    """Next.js file-convention routes (app router `route`/`page`, and `pages/`)."""
    parts = rel.replace("\\", "/").split("/")
    stem = os.path.splitext(parts[-1])[0]
    if stem in ("route", "page") and "app" in parts:
        i = len(parts) - 1 - parts[::-1].index("app")
        path = _next_path(parts[i + 1:-1])
        if stem == "route":
            methods = NEXT_METHOD_RE.findall(text) or ["ANY"]
            return [{"method": m, "path": path, "file": rel} for m in methods]
        return [{"method": "PAGE", "path": path, "file": rel}]
    if "pages" in parts:
        i = parts.index("pages")
        is_api = len(parts) > i + 1 and parts[i + 1] == "api"
        segs = list(parts[i + 1:-1]) + ([] if stem == "index" else [stem])
        return [{"method": "ANY" if is_api else "PAGE", "path": _next_path(segs),
                 "file": rel}]
    return []


def _outbound(text: str, rel: str) -> List[Dict[str, object]]:
    return [{"host": m.group(1), "port": int(m.group(2)),
             "path": m.group(3) or "", "file": rel}
            for m in URL_RE.finditer(text)]


def _entrypoints(root: str, rel_files: Sequence[Tuple[str, str, str]]) -> List[Dict[str, str]]:
    """Conventional entry files plus npm `main`/`start`."""
    found: List[Dict[str, str]] = []
    top_level = {rel for _f, rel, _e in rel_files if os.sep not in rel}
    for name, kind in ENTRYPOINT_NAMES.items():
        if name in top_level:
            found.append({"file": name, "kind": kind})
    text = read_text(os.path.join(root, "package.json"))
    if text:
        try:
            data = json.loads(text)
        except ValueError:
            return found
        if isinstance(data.get("main"), str):
            found.append({"file": data["main"], "kind": "package.main"})
        start = (data.get("scripts") or {}).get("start")
        if isinstance(start, str):
            found.append({"file": "npm start: " + start, "kind": "package.start"})
    return found


def _layers(root: str) -> List[Dict[str, object]]:
    """Top-level directories with their source-file counts."""
    out: List[Dict[str, object]] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        full = os.path.join(root, name)
        if not os.path.isdir(full) or is_skipped(name):
            continue
        count = sum(1 for _ in iter_files(full, SOURCE_EXTS))
        if count:
            out.append({"name": name, "files": count})
    return sorted(out, key=lambda x: -int(x["files"]))


def _dedupe_endpoints(items: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out: List[Dict[str, str]] = []
    for e in items:
        key = (e["method"], e["path"], e["file"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return sorted(out, key=lambda x: (x["path"], x["method"]))


def _resolve_outbound(calls: Sequence[Dict[str, object]], own_port: Optional[int],
                      names: Dict[int, str]) -> List[Dict[str, object]]:
    """Drop self-calls, dedupe by host:port, attach the registered project name."""
    seen = set()
    out: List[Dict[str, object]] = []
    for call in calls:
        port = int(call["port"])
        if own_port and port == own_port:
            continue
        key = (call["host"], port)
        if key in seen:
            continue
        seen.add(key)
        local = str(call["host"]) in LOCAL_HOSTS
        out.append({**call, "project": names.get(port) if local else None,
                    "local": local})
    return sorted(out, key=lambda c: (c["project"] is None, int(c["port"])))


def scan(root: str, reg: Optional[Registry] = None,
         max_files: int = 1200) -> Dict[str, object]:
    """Static topology of one project."""
    reg = reg if reg is not None else Registry([], "")
    real_root = os.path.realpath(os.path.expanduser(root))
    entry = next((e for e in reg.entries if e.real_path == real_root), None)
    names = reg.port_names()

    rel_files = list(iter_files(real_root, SOURCE_EXTS, max_files))
    exposed: List[Dict[str, str]] = []
    calls: List[Dict[str, object]] = []
    for full, rel, ext in rel_files:
        text = read_text(full)
        if not text:
            continue
        if ext in (".py", ".rb", ".go"):
            exposed += _flask_endpoints(text, rel)
        else:
            exposed += _express_endpoints(text, rel)
            exposed += _next_endpoints(rel, text)
        calls += _outbound(text, rel)

    own_port = entry.port if entry else None
    return {
        "project": entry.name if entry else os.path.basename(real_root.rstrip(os.sep)),
        "root": real_root,
        "port": own_port,
        "entrypoints": _entrypoints(real_root, rel_files),
        "endpoints": _dedupe_endpoints(exposed),
        "calls": _resolve_outbound(calls, own_port, names),
        "layers": _layers(real_root),
        "scanned": len(rel_files),
        "truncated": len(rel_files) >= max_files,
    }


def graph(reg: Registry, max_files: int = 600) -> Dict[str, object]:
    """Cross-project call graph built from every registered project on disk."""
    nodes: List[Dict[str, object]] = []
    edges: List[Dict[str, object]] = []
    for entry in reg.sorted():
        if not entry.exists():
            continue
        topo = scan(entry.real_path, reg, max_files)
        nodes.append({"name": entry.name, "port": entry.port,
                      "endpoints": len(topo["endpoints"])})
        for call in topo["calls"]:
            if call.get("project") and call["project"] != entry.name:
                edges.append({"from": entry.name, "to": call["project"],
                              "port": call["port"]})
    seen = set()
    unique = []
    for e in edges:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return {"nodes": nodes, "edges": unique}
