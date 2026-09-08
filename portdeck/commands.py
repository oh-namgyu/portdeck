"""Command handlers — one function per subcommand.

Each takes the parsed arguments and a loaded registry, prints, and returns the
process exit code. The parser lives in `cli`; nothing here knows about argparse
beyond reading attributes off the namespace.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Sequence

from . import allocate, containers, doctor, live, render, topology, watch
from .discover import Discovery, discover
from .registry import Entry, Registry, tilde_path

DEFAULT_DEPTH = 2


def _emit(args: argparse.Namespace, payload: object, text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif text:
        print(text)


def cmd_ls(args: argparse.Namespace, reg: Registry) -> int:
    if not reg.entries:
        print("registry is empty ({}) — try: portdeck scan ~/code --write".format(reg.path))
        return 0
    listeners, cwds = doctor.snapshot()
    statuses = [doctor.entry_status(e, listeners, cwds) for e in reg.sorted()]
    _emit(args, statuses, render.status_rows(statuses))
    return 0


def cmd_scan(args: argparse.Namespace, reg: Registry) -> int:
    roots = args.roots or [os.getcwd()]
    found = discover(roots, args.depth)
    reg_ports = {e.real_path: e.port for e in reg.entries if e.real_path}
    if args.write:
        return _write_scan(args, reg, found)
    _emit(args, [d.to_dict() for d in found], render.discoveries(found, reg_ports))
    if not getattr(args, "json", False) and found:
        print("\n{} scanned — rerun with --write to save".format(
            render.plural(len(found), "project")))
    return 0


def _write_scan(args: argparse.Namespace, reg: Registry,
                found: Sequence[Discovery]) -> int:
    """Apply a scan to the registry and report what changed."""
    actions: Dict[str, int] = {"added": 0, "updated": 0, "unchanged": 0}
    changes: List[str] = []
    for d in found:
        if d.port is None:
            continue
        action = reg.upsert(Entry(d.name, d.port, tilde_path(d.root), source=d.source))
        actions[action] += 1
        if action != "unchanged":
            changes.append("{} {} :{}".format(action, d.name, d.port))
    path = reg.save()
    summary = "{added} added, {updated} updated, {unchanged} unchanged → {path}".format(
        path=path, **actions)
    _emit(args, {"summary": actions, "changes": changes, "registry": path},
          "\n".join(changes + [summary]) if changes else summary)
    return 0


def cmd_doctor(args: argparse.Namespace, reg: Registry) -> int:
    found = discover(args.roots, DEFAULT_DEPTH) if args.roots else None
    items = doctor.run(reg, found, include_stale=args.stale)
    if args.fix:
        return _apply_fixes(args, reg, items)
    _emit(args, [f.to_dict() for f in items], render.findings(items))
    return 1 if any(f.severity == "high" for f in items) else 0


FIXABLE = ("drift", "unregistered")


def _apply_fixes(args: argparse.Namespace, reg: Registry,
                 items: Sequence[doctor.Finding]) -> int:
    """Apply the findings that have one obvious resolution.

    Collisions and squatters are deliberately left alone — choosing which
    project moves, or which process dies, is not the tool's call.
    """
    before = {f.port for f in doctor.check_collisions(reg)}
    applied: List[str] = []
    for finding in items:
        if finding.check not in FIXABLE or not finding.detail:
            continue
        detail = finding.detail
        entry = Entry(str(detail["project"]), int(detail["port"]),
                      tilde_path(str(detail.get("path") or "")), source="fix")
        action = reg.upsert(entry)
        if action != "unchanged":
            applied.append("{} {} :{}".format(action, entry.name, entry.port))
    skipped = [f for f in items if f.check not in FIXABLE]
    if applied:
        reg.save()
    # Taking the code's word for it can put two projects on the same port.
    new_clashes = [f for f in doctor.check_collisions(reg) if f.port not in before]
    text = "\n".join(applied + [render.paint(f.message, "yellow") for f in new_clashes]
                     + ["{} applied, {} left for you".format(len(applied), len(skipped))])
    _emit(args, {"applied": applied, "skipped": [f.to_dict() for f in skipped],
                 "new_collisions": [f.to_dict() for f in new_clashes]}, text)
    return 1 if new_clashes or any(f.severity == "high" for f in skipped) else 0


def cmd_free(args: argparse.Namespace, reg: Registry) -> int:
    ports = list(allocate.suggest(reg, args.count, args.start, args.near))
    if not ports:
        print("no free port in that range", file=sys.stderr)
        return 2
    _emit(args, {"ports": ports}, "\n".join(str(p) for p in ports))
    return 0


def cmd_watch(args: argparse.Namespace, reg: Registry) -> int:
    return watch.run(reg, args.interval)


def cmd_map(args: argparse.Namespace, reg: Registry) -> int:
    entry = reg.find(args.target)
    root = entry.real_path if entry else os.path.realpath(os.path.expanduser(args.target))
    if not os.path.isdir(root):
        print("no project found for {!r}".format(args.target), file=sys.stderr)
        return 2
    topo = topology.scan(root, reg)
    text = render.topology_mermaid(topo) if args.mermaid else render.topology(topo)
    _emit(args, topo, text)
    return 0


def cmd_graph(args: argparse.Namespace, reg: Registry) -> int:
    data = topology.graph(reg)
    text = render.graph_mermaid(data) if args.mermaid else render.graph_text(data)
    _emit(args, data, text)
    return 0


def cmd_who(args: argparse.Namespace, reg: Registry) -> int:
    listener = live.owner_of(args.port)
    entry = next((e for e in reg.entries if e.port == args.port), None)
    box = containers.by_port().get(args.port) if listener else None
    payload = {"port": args.port, "registered": entry.name if entry else None,
               "listener": listener.to_dict() if listener else None,
               "cwd": live.cwd_of(listener.pid) if listener else "",
               "container": box.to_dict() if box else None}
    _emit(args, payload, _who_text(payload, args.port))
    return 0


def _who_text(payload: Dict[str, object], port: int) -> str:
    lines = []
    if payload["registered"]:
        lines.append("registered to {}".format(payload["registered"]))
    box = payload["container"]
    if box:
        lines.append("published by container {} ({})".format(box["name"], box["image"]))
        lines.append("to free it: docker stop {}".format(box["name"]))
        return "\n".join(lines)
    listener = payload["listener"]
    if not listener:
        lines.append("port {} is free".format(port))
        return "\n".join(lines)
    lines.append("held by {} (pid {}){}".format(
        listener["command"], listener["pid"],
        " in {}".format(payload["cwd"]) if payload["cwd"] else ""))
    hint = live.system_hint(str(listener["command"]), port)
    lines.append("  {}".format(hint) if hint
                 else "to free it: kill {}".format(listener["pid"]))
    return "\n".join(lines)


def cmd_add(args: argparse.Namespace, reg: Registry) -> int:
    path = tilde_path(os.path.realpath(os.path.expanduser(args.path))) if args.path else ""
    action = reg.upsert(Entry(args.name, args.port, path, args.note))
    saved = reg.save()
    _emit(args, {"action": action, "registry": saved},
          "{} {} :{} → {}".format(action, args.name, args.port, saved))
    return 0


def cmd_rm(args: argparse.Namespace, reg: Registry) -> int:
    entry = reg.find(args.target)
    if not entry:
        print("no entry matches {!r}".format(args.target), file=sys.stderr)
        return 2
    reg.entries.remove(entry)
    saved = reg.save()
    _emit(args, {"removed": entry.to_dict(), "registry": saved},
          "removed {} :{} → {}".format(entry.name, entry.port, saved))
    return 0
