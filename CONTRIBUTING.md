# Contributing to portdeck

Thanks for your interest! Bug reports, missed or wrong port discoveries (with
the snippet that caused them) and pull requests are welcome.

## Development setup

```sh
python -m venv .venv && source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -t .
portdeck --help
```

CI runs the suite on Ubuntu and macOS with Python 3.9 and 3.12, then smokes
`portdeck --help` and `portdeck scan . --depth 1`.

## Guidelines

- **Zero runtime dependencies.** Standard library only. `lsof` and `docker`
  are optional system tools; every feature that uses them must degrade
  cleanly when they are missing.
- **Read-only apart from the registry.** portdeck never stops a process,
  edits source code or writes any file other than the registry. Read
  [SECURITY.md](SECURITY.md) before changing what it touches.
- **Static scans only.** Discovery and `map`/`graph` read source text; they
  must never import or execute a project's code.
- **Evidence for every port.** A new discovery pattern reports the file and
  line it came from and needs a test in `tests/test_discover.py`.
- **No real data in fixtures.** Use neutral example ports, names and paths.
- Add a regression test for any bug fix.

## Pull requests

Keep PRs focused on one change, describe what changed and how you verified
it, and make sure the test suite is green before opening one.
