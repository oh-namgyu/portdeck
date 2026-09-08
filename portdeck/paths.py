"""Shared filesystem helpers — directory skipping, capped walks, safe reads.

Both the port scanner and the topology scanner walk user project trees, so the
caps and the skip list live here to keep the two honest about the same limits.
"""

from __future__ import annotations

import os
from typing import Iterator, List, Optional, Sequence, Tuple

SKIP_DIRS = {
    "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build",
    "out", ".next", ".nuxt", "target", "vendor", "coverage", "site-packages",
    "logs", "tmp", ".cache", ".git", ".idea", ".vscode", "Pods",
}
SOURCE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".go", ".rb"}
SCAN_EXTS = SOURCE_EXTS | {".html"}

# Project markers, ordered by how strongly they imply "this is a project root".
MARKERS = ("package.json", "pyproject.toml", "requirements.txt", "go.mod",
           "Gemfile", "docker-compose.yml", "docker-compose.yaml", "Cargo.toml",
           ".git")

MAX_FILES = 2500
MAX_BYTES = 200_000


def is_skipped(name: str) -> bool:
    return name in SKIP_DIRS or (name.startswith(".") and name != ".git")


def read_text(path: str, limit: int = MAX_BYTES) -> str:
    """Read a file as text, truncated and never raising."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def iter_files(root: str, exts: Optional[Sequence[str]] = None,
               max_files: int = MAX_FILES) -> Iterator[Tuple[str, str, str]]:
    """Yield (abspath, relpath, ext) for source files under root, capped."""
    wanted = set(exts) if exts is not None else SCAN_EXTS
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_skipped(d)]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in wanted:
                continue
            count += 1
            if count > max_files:
                return
            full = os.path.join(dirpath, name)
            yield full, os.path.relpath(full, root), ext


def is_project(path: str) -> bool:
    return any(os.path.exists(os.path.join(path, m)) for m in MARKERS)


def find_projects(roots: Sequence[str], depth: int = 2) -> List[str]:
    """Find project roots under the given roots.

    Descent stops at the first directory that looks like a project, so a
    monorepo root shadows its packages only when it carries a marker itself.
    """
    found: List[str] = []
    seen = set()
    for root in roots:
        base = os.path.realpath(os.path.expanduser(root))
        if not os.path.isdir(base):
            continue
        _descend(base, depth, found, seen)
    return sorted(found)


def _descend(path: str, depth: int, found: List[str], seen: set) -> None:
    if path in seen:
        return
    seen.add(path)
    if is_project(path):
        found.append(path)
        return
    if depth <= 0:
        return
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return
    for name in names:
        child = os.path.join(path, name)
        if os.path.isdir(child) and not os.path.islink(child) and not is_skipped(name):
            _descend(child, depth - 1, found, seen)
