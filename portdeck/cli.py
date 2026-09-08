"""Command line interface.

    portdeck ls                 registered projects and what is actually running
    portdeck scan [ROOT...]     find projects and the ports they declare
    portdeck doctor [--fix]     collisions, drift, squatters, orphans
    portdeck free [N]           a port nothing is using
    portdeck watch              ports as they start and stop
    portdeck map TARGET         one project's routes and outbound calls
    portdeck graph              how your local services call each other
    portdeck who PORT           what holds a port right now
    portdeck add / rm           edit the registry by hand
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Optional, Sequence

from . import watch
from .commands import (DEFAULT_DEPTH, cmd_add, cmd_doctor, cmd_free, cmd_graph,
                       cmd_ls, cmd_map, cmd_rm, cmd_scan, cmd_watch, cmd_who)
from .registry import Registry


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


AddParser = Callable[[str, str], argparse.ArgumentParser]


def build_parser() -> argparse.ArgumentParser:
    common = _global_options()
    parser = argparse.ArgumentParser(
        prog="portdeck", parents=[common],
        description="A registry and map for your local dev ports.")
    sub = parser.add_subparsers(dest="command")

    def add(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    _add_state_commands(add)
    _add_map_commands(add)
    _add_edit_commands(add)
    return parser


def _add_state_commands(add: AddParser) -> None:
    """Commands that answer "what is going on": ls, scan, doctor, free, watch."""
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
    doc.add_argument("--fix", action="store_true",
                     help="apply what is safely fixable: drift and unregistered projects")

    free = add("free", "suggest a port nothing is using")
    free.add_argument("count", nargs="?", type=int, default=1,
                      help="how many to suggest (default: 1)")
    free.add_argument("--from", dest="start", type=int, default=None,
                      help="lowest port to consider")
    free.add_argument("--near", default=None,
                      help="keep the suggestion in the same block as this project")

    wat = add("watch", "print ports as they start and stop")
    wat.add_argument("--interval", type=float, default=watch.DEFAULT_INTERVAL,
                     help="seconds between looks (default: 2)")


def _add_map_commands(add: AddParser) -> None:
    """Commands that draw the shape of things: map, graph, who."""
    mp = add("map", "routes and outbound calls of one project")
    mp.add_argument("target", help="project name, port, or path")
    mp.add_argument("--mermaid", action="store_true", help="emit a mermaid flowchart")

    gr = add("graph", "cross-project call graph")
    gr.add_argument("--mermaid", action="store_true", help="emit a mermaid flowchart")

    who = add("who", "what is listening on a port")
    who.add_argument("port", type=int)


def _add_edit_commands(add: AddParser) -> None:
    """Commands that change the registry by hand: add, rm."""
    new = add("add", "register a project")
    new.add_argument("name")
    new.add_argument("port", type=int)
    new.add_argument("--path", default="", help="project directory")
    new.add_argument("--note", default="")

    rm = add("rm", "remove a registry entry")
    rm.add_argument("target", help="project name or port")


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
        "free": cmd_free, "watch": cmd_watch,
    }[args.command]
    return handler(args, reg)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
