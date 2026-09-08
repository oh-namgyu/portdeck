"""Container attribution.

On a developer machine a surprising share of "who is on this port?" answers are
"a container you started in another project last month". `lsof` only ever says
`com.docker.backend`, so ask Docker directly and map published host ports to
container names. Docker is optional: no daemon, no CLI, no problem.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Dict, Iterable, Optional

DOCKER_TIMEOUT = 5.0
FORMAT = "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}"


class Container:
    """A running container and one of its published ports."""

    __slots__ = ("cid", "name", "image")

    def __init__(self, cid: str, name: str, image: str) -> None:
        self.cid = cid
        self.name = name
        self.image = image

    def to_dict(self) -> Dict[str, str]:
        return {"id": self.cid, "name": self.name, "image": self.image}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Container({!r}, {!r})".format(self.name, self.image)


def _docker_binary() -> Optional[str]:
    return shutil.which("docker")


def _run_docker() -> str:
    binary = _docker_binary()
    if not binary:
        return ""
    try:
        proc = subprocess.run([binary, "ps", "--format", FORMAT],
                              capture_output=True, text=True, timeout=DOCKER_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


def host_ports(spec: str) -> Iterable[int]:
    """Host ports out of a docker `Ports` column.

    Entries look like `0.0.0.0:8081->80/tcp, :::8081->80/tcp, 9000/tcp`; only
    the published ones (those with `->`) are reachable from the host.
    """
    for part in spec.split(","):
        part = part.strip()
        if "->" not in part:
            continue
        left = part.split("->", 1)[0]
        tail = left.rsplit(":", 1)[-1]
        if tail.isdigit():
            yield int(tail)


def parse(text: str) -> Dict[int, Container]:
    """Parse `docker ps` output into host port -> container."""
    out: Dict[int, Container] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        cid, name, image, ports = (f.strip() for f in fields[:4])
        container = Container(cid, name, image)
        for port in host_ports(ports):
            out.setdefault(port, container)
    return out


def by_port() -> Dict[int, Container]:
    """Published host ports of every running container ({} without Docker)."""
    return parse(_run_docker())
