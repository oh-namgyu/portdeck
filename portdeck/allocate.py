"""Free-port suggestion.

`doctor` tells you two projects want the same port; this is the other half of
that sentence — a port that is free in both senses: nobody has registered it,
and nothing is listening on it.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from . import live
from .registry import Registry

DEFAULT_RANGE = (4000, 9999)
# Ports that are formally free but a bad suggestion: dev servers, databases and
# system services grab them the moment you are not looking.
AVOID = {
    3000, 3001, 4200, 5000, 5432, 5173, 6379, 7000, 8000, 8080, 8443, 8888,
    9000, 9090, 9200, 27017,
}


def taken(reg: Registry, listeners: Optional[Dict[int, live.Listener]] = None) -> Set[int]:
    """Every port that is spoken for, registered or live."""
    listeners = live.listening_ports() if listeners is None else listeners
    return set(reg.by_port()) | set(listeners) | AVOID


def free_ports(reg: Registry, count: int = 1, start: Optional[int] = None,
               end: Optional[int] = None,
               listeners: Optional[Dict[int, live.Listener]] = None) -> List[int]:
    """The lowest `count` free ports at or after `start`."""
    low = DEFAULT_RANGE[0] if start is None else max(1, start)
    high = DEFAULT_RANGE[1] if end is None else end
    used = taken(reg, listeners)
    found: List[int] = []
    for port in range(low, high + 1):
        if port in used:
            continue
        found.append(port)
        if len(found) >= count:
            break
    return found


def next_in_block(reg: Registry, sibling: int, size: int = 100,
                  listeners: Optional[Dict[int, live.Listener]] = None) -> Optional[int]:
    """A free port in the same hundred-block as an existing one.

    Ports tend to be grouped by intent (`61xx` for games, `50xx` for services);
    keeping a new project near its siblings preserves that.
    """
    base = (sibling // size) * size
    found = free_ports(reg, 1, base, base + size - 1, listeners)
    return found[0] if found else None


def suggest(reg: Registry, count: int = 1, start: Optional[int] = None,
            near: Optional[str] = None) -> Sequence[int]:
    """Suggest ports, optionally next to a named project's own port."""
    listeners = live.listening_ports()
    if near:
        entry = reg.find(near)
        if entry:
            block = next_in_block(reg, entry.port, listeners=listeners)
            if block is not None and count == 1:
                return [block]
            start = start if start is not None else (entry.port // 100) * 100
    return free_ports(reg, count, start, None, listeners)
