"""Terminal rendering — plain, aligned, and pipe-safe.

Colour is used only when stdout is a TTY and NO_COLOR is unset, so piping into
grep or a file gives clean text.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence

COLORS = {"red": "31", "yellow": "33", "green": "32", "cyan": "36", "dim": "2"}
SEVERITY_COLOR = {"high": "red", "medium": "yellow", "low": "dim"}


def use_color(stream: Optional[object] = None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text: str, color: str, enabled: Optional[bool] = None) -> str:
    enabled = use_color() if enabled is None else enabled
    if not enabled or color not in COLORS:
        return text
    return "\033[{}m{}\033[0m".format(COLORS[color], text)


def plural(count: int, noun: str) -> str:
    return "{} {}{}".format(count, noun, "" if count == 1 else "s")


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Left-aligned columns sized to their content."""
    if not rows:
        return ""
    cells = [list(headers)] + [[str(c) for c in row] for row in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    lines = []
    for index, row in enumerate(cells):
        line = "  ".join(value.ljust(widths[i]) for i, value in enumerate(row)).rstrip()
        lines.append(paint(line, "dim") if index == 0 else line)
    return "\n".join(lines)


def status_rows(statuses: Sequence[Dict[str, Any]]) -> str:
    """`portdeck ls` — one row per registered project."""
    rows: List[List[str]] = []
    for s in statuses:
        if not s["running"]:
            state = paint("·  stopped", "dim")
        elif s["owned"]:
            state = paint("●  running", "green")
        else:
            state = paint("!  foreign", "red")
        who = "{} ({})".format(s["command"], s["pid"]) if s["running"] else ""
        rows.append([str(s["port"]), str(s["name"]), state, who, str(s["path"])])
    return table(["PORT", "PROJECT", "STATE", "HELD BY", "PATH"], rows)


def findings(items: Sequence[Any]) -> str:
    """`portdeck doctor` — severity-tagged lines with a suggested fix."""
    if not items:
        return paint("no problems found", "green")
    lines = []
    for f in items:
        tag = paint("[{}]".format(f.severity), SEVERITY_COLOR.get(f.severity, "dim"))
        lines.append("{} {} — {}".format(tag, paint(f.check, "cyan"), f.message))
        if f.fix:
            lines.append("       fix: {}".format(f.fix))
    return "\n".join(lines)


def discoveries(items: Sequence[Any], reg_ports: Dict[str, int]) -> str:
    """`portdeck scan` — discovered projects against what the registry holds."""
    rows: List[List[str]] = []
    for d in items:
        current = reg_ports.get(d.root)
        if d.port is None:
            verdict = paint("no port found", "dim")
        elif current is None:
            verdict = paint("new", "green")
        elif current == d.port:
            verdict = "ok"
        else:
            verdict = paint("differs (registry {})".format(current), "yellow")
        ev = d.evidence[0] if d.evidence else None
        where = "{}:{} [{}]".format(ev.file, ev.line, ev.kind) if ev else ""
        if ev and ev.incidental:
            where += paint("  (from a test/example — check this one)", "yellow")
        rows.append([str(d.port or "-"), d.name, verdict, where])
    return table(["PORT", "PROJECT", "STATUS", "EVIDENCE"], rows)


def topology(topo: Dict[str, Any]) -> str:
    """`portdeck map` — one project's entry points, routes and outbound calls."""
    head = "{}{}".format(topo["project"],
                         "  :{}".format(topo["port"]) if topo["port"] else "")
    out = [paint(head, "cyan"), paint(str(topo["root"]), "dim"), ""]
    out += _section("entrypoints", ["{}  ({})".format(e["file"], e["kind"])
                                    for e in topo["entrypoints"]])
    out += _section("endpoints", ["{:6} {}  {}".format(e["method"], e["path"],
                                                       paint(e["file"], "dim"))
                                  for e in topo["endpoints"]])
    out += _section("outbound", [_call_line(c) for c in topo["calls"]])
    out += _section("layers", ["{}  ({})".format(l["name"], plural(int(l["files"]), "file"))
                               for l in topo["layers"]])
    note = "scanned {}{}".format(plural(int(topo["scanned"]), "file"),
                                 " (truncated)" if topo["truncated"] else "")
    out.append(paint(note, "dim"))
    return "\n".join(out)


def topology_mermaid(topo: Dict[str, Any]) -> str:
    """Mermaid flowchart for one project: its routes in, its calls out."""
    own = _mermaid_id(str(topo["project"]))
    label = "{}<br/>:{}".format(topo["project"], topo["port"] or "?")
    lines = ["flowchart LR", '  {}["{}"]'.format(own, label)]
    for endpoint in topo["endpoints"][:20]:
        node = _mermaid_id("ep_{}_{}".format(endpoint["method"], endpoint["path"]))
        lines.append('  {}(["{} {}"]) --> {}'.format(
            node, endpoint["method"], endpoint["path"], own))
    for call in topo["calls"]:
        target = str(call.get("project") or "{}:{}".format(call["host"], call["port"]))
        lines.append("  {} -->|:{}| {}[\"{}\"]".format(
            own, call["port"], _mermaid_id(target), target))
    return "\n".join(lines)


def _call_line(call: Dict[str, Any]) -> str:
    target = "{}:{}{}".format(call["host"], call["port"], call["path"])
    if call.get("project"):
        return "{}  → {}".format(target, paint(str(call["project"]), "green"))
    return "{}  {}".format(target, paint("(unregistered)" if call.get("local") else "",
                                         "dim")).rstrip()


def _section(title: str, lines: Sequence[str]) -> List[str]:
    if not lines:
        return []
    out = [paint(title.upper(), "dim")]
    out += ["  " + line for line in lines]
    out.append("")
    return out


def graph_text(graph: Dict[str, Any]) -> str:
    """`portdeck graph` — edges as plain arrows."""
    edges = graph["edges"]
    if not edges:
        return paint("no cross-project calls found", "dim")
    rows = [[e["from"], "→", "{} :{}".format(e["to"], e["port"])] for e in edges]
    return table(["FROM", "", "TO"], rows)


def graph_mermaid(graph: Dict[str, Any]) -> str:
    """Mermaid `flowchart` source for the cross-project graph."""
    edges = graph["edges"]
    connected = {e["from"] for e in edges} | {e["to"] for e in edges}
    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        if connected and node["name"] not in connected:
            continue  # isolated services would drown the diagram
        lines.append('  {}["{}<br/>:{}"]'.format(
            _mermaid_id(str(node["name"])), node["name"], node["port"]))
    for edge in graph["edges"]:
        lines.append("  {} -->|:{}| {}".format(
            _mermaid_id(str(edge["from"])), edge["port"], _mermaid_id(str(edge["to"]))))
    return "\n".join(lines)


def _mermaid_id(name: str) -> str:
    return "n_" + "".join(c if c.isalnum() else "_" for c in name)
