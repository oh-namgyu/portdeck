# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-08

Initial public release.

### Added

- `portdeck scan` finds the ports projects declare, ranked by evidence kind
  (`compose`, `listen`, `config`, `script`, `env`, `const`), with the file and
  line for every finding. Ports from tests, fixtures and examples are used
  only as a fallback. Nothing is written without `--write`.
- A JSON registry resolved from `$PORTDECK_REGISTRY`, `./portdeck.json` or
  `~/.config/portdeck/registry.json`. A bare list is accepted on load, paths
  under `$HOME` are stored as `~/...`, and a malformed record does not discard
  the rest. `portdeck add` and `portdeck rm` edit it by hand.
- `portdeck ls` shows registered projects with their live state (running,
  stopped or foreign) and the process holding each port, via `lsof` when it
  is available.
- `portdeck doctor` checks for collisions, squatters, drift, missing paths,
  orphans, unregistered projects (`--scan ROOT`) and stale projects
  (`--stale`), and exits 1 on any high-severity finding. `--fix` applies only
  drift and unregistered-project fixes.
- `portdeck free` suggests unused ports (`count`, `--from`, `--near`),
  skipping registered, listening and commonly used ports.
- `portdeck watch` reports ports as they start, stop or change process.
- `portdeck who <port>` explains what holds a port. Published container ports
  are attributed to the container when the `docker` CLI and daemon are
  available.
- `portdeck map` and `portdeck graph` (with `--mermaid`) statically scan
  Flask/FastAPI, Express and Next.js routes and `http://host:port` literals to
  show endpoints and calls between registered projects. Nothing is imported or
  executed.
- `--json` and `--registry` on every command.
- Read-only apart from the registry file; no process is ever stopped. No
  third-party dependencies, Python 3.9+.
