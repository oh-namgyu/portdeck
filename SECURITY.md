# Security

## Reporting a problem

Please open an issue at <https://github.com/oh-namgyu/portdeck/issues>. There is
no private disclosure channel; if a finding should not be public, say so in a
short issue without the details and a maintainer will follow up.

## What portdeck touches

Everything runs locally and nothing is sent anywhere — portdeck has no network
client and no third-party dependencies.

| Action | Scope |
|---|---|
| Reading source files | The roots you pass to `scan`/`map`, capped per project |
| Listing listeners | `lsof -nP -iTCP -sTCP:LISTEN` and `lsof -p PID -d cwd` |
| Probing a port | A TCP connect to `127.0.0.1:PORT`, closed immediately |
| Writing | The registry file only, and only on `scan --write`, `add`, `rm` |

portdeck never stops a process. `who` prints the pid and the command you could
run; running it is your decision.

## Things worth knowing

- **The registry may be sensitive.** Project names and paths (often under
  `$HOME`) are written to it. Check before committing one to a shared repo;
  paths under `$HOME` are stored as `~/...` to reduce, not remove, that risk.
- **Scanning reads whatever you point it at.** `scan` walks the roots you give
  it, including files you may not have written. It reads at most 200KB per file
  and never executes anything.
- **`--json` output embeds file paths and snippets** from your source. Treat it
  as you would the code itself.
