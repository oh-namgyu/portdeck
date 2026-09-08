"""Command line interface.

    portdeck ls                 registered projects and what is actually running
    portdeck scan [ROOT...]     find projects and the ports they declare
    portdeck doctor             collisions, drift, squatters, orphans
    portdeck map TARGET         one project's routes and outbound calls
    portdeck graph              how your local services call each other
    portdeck who PORT           what holds a port right now
    portdeck add / rm           edit the registry by hand
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Sequence

from . import doctor, live, render, topology
from .discover import Discovery, discover
from .registry import Entry, Registry, tilde_path

DEFAULT_DEPTH = 2


def _global_options() -> argparse.ArgumentParser:
    """Options accepted both before and after the subcommand.

    `parents=` shares one action object between the top-level parser and every
    subparser, so an unset subcommand copy would otherwise overwrite a value
    given before the subcommand. SUPPRESS leaves the attribute off the namespace
    entirely instead; the readers below supply the real defaults.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--registry", default=argparse.SUPPRESS,
                        help="registry file (default: $PORTDECK_REGISTRY, ./portdeck.json, "
                             "~/.config/portdeck/registry.json)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _global_options()
    parser = argparse.ArgumentParser(
        prog="portdeck", parents=[common],
        description="A registry and map for your local dev ports.")
    sub = parser.add_subparsers(dest="command")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    add("ls", "registered projects and their live state")

    scan = add("scan", "discover projects and the ports they declare")
    scan.add_argument("roots", nargs="*", default=None, help="directories to scan")
    scan.add_argument("--depth", type=int, default=DEFAULT_DEPTH,
                      help="how deep to look for project roots (default: 2)")
    scan.add_argument("--write", action="store_true", help="save findings to the registry")

    doc = add("doctor", "report port problems")
    doc.add_argument("--scan", nargs="*", dest="roots", default=None,
                     help="also report unregistered projects under these roots")
    doc.add_argument("--stale", action="store_true", help="include long-idle projects")

    mp = add("map", "routes and outbound calls of one project")
    mp.add_argument("target", help="project name, port, or path")
    mp.add_argument("--mermaid", action="store_true", help="emit a mermaid flowchart")

    gr = add("graph", "cross-project call graph")
    gr.add_argument("--mermaid", action="store_true", help="emit a mermaid flowchart")

    who = add("who", "what is listening on a port")
    who.add_argument("port", type=int)

    new = add("add", "register a project")
    new.add_argument("name")
    new.add_argument("port", type=int)
    new.add_argument("--path", default="", help="project directory")
    new.add_argument("--note", default="")

    rm = add("rm", "remove a registry entry")
    rm.add_argument("target", help="project name or port")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    reg = Registry.load(getattr(args, "registry", None))
    handler = {
        "ls": cmd_ls, "scan": cmd_scan, "doctor": cmd_doctor, "map": cmd_map,
        "graph": cmd_graph, "who": cmd_who, "add": cmd_add, "rm": cmd_rm,
    }[args.command]
    return handler(args, reg)


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
    _emit(args, [f.to_dict() for f in items], render.findings(items))
    return 1 if any(f.severity == "high" for f in items) else 0


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
    payload = {"port": args.port, "registered": entry.name if entry else None,
               "listener": listener.to_dict() if listener else None,
               "cwd": live.cwd_of(listener.pid) if listener else ""}
    _emit(args, payload, _who_text(payload, args.port))
    return 0


def _who_text(payload: Dict[str, object], port: int) -> str:
    lines = []
    if payload["registered"]:
        lines.append("registered to {}".format(payload["registered"]))
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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
