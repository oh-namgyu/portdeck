# portdeck

[![CI](https://github.com/oh-namgyu/portdeck/actions/workflows/ci.yml/badge.svg)](https://github.com/oh-namgyu/portdeck/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

> **한글 요약** — 로컬에 프로젝트가 수십 개 쌓이면 "이 포트가 누구 거였지?"가 시작됩니다.
> portdeck 은 프로젝트를 훑어 **코드가 선언한 포트를 근거(파일:줄)와 함께** 찾아 등록부를 만들고,
> 지금 그 포트를 **실제로 누가 점유 중인지**(pid·실행 디렉토리) 대조해 충돌·표류·무단점유를 진단합니다.
> `map`·`graph` 는 각 서비스의 라우트와 서비스 간 호출 관계를 정적 스캔으로 그려 줍니다.
> 의존성 0 (표준 라이브러리만), 읽기 전용 — 프로세스를 죽이거나 코드를 고치지 않습니다.

Keep a registry of the ports your local projects use, find the ones you never wrote
down, and see who is actually holding them right now.

## The problem

You have thirty projects on this machine. Something is on `:5000`. Is it the API you
started last week, a container you forgot, or macOS itself? Your notes say project X
owns `:6040`, but the code says otherwise — and you find out when two services fight
over a socket at 2am.

portdeck answers four questions:

| Question | Command |
|---|---|
| What ports do my projects declare? | `portdeck scan ~/code` |
| What is registered, and what is running? | `portdeck ls` |
| What is wrong right now? | `portdeck doctor` |
| Who calls whom, and on which port? | `portdeck graph` |

## Install

```bash
pip install -e .          # or: pipx install .
portdeck --help
```

Python 3.9+. No third-party dependencies. `lsof` is used when present (macOS and Linux
ship it); without it portdeck still reports whether a port is listening, just not who
holds it.

## Use

### Build the registry from what your code actually says

```console
$ portdeck scan ~/code --depth 2
PORT  PROJECT       STATUS                   EVIDENCE
3000  web-frontend  new                      package.json:0 [script]
4400  api-gateway   new                      app.py:212 [listen]
6040  chronicle     differs (registry 6041)  chronicle/config.py:4 [const]
8081  billing       new                      docker-compose.yml:7 [compose]
-     scratchpad    no port found

5 projects scanned — rerun with --write to save
```

Nothing is written until you pass `--write`. Every row carries the file and line the
port came from, so a wrong guess is a five-second check rather than a mystery.

### See what is actually running

```console
$ portdeck ls
PORT  PROJECT       STATE       HELD BY              PATH
3000  web-frontend  ●  running  node (41290)         ~/code/web-frontend
5000  daily-news    !  foreign  ControlCenter (668)  ~/code/daily-news
4400  api-gateway   ·  stopped                       ~/code/api-gateway
```

`foreign` means the port is busy, but the process holding it is running from somewhere
other than the project that registered it.

### Diagnose

```console
$ portdeck doctor
[high] squatter — daily-news owns port 5000 but it is held by ControlCenter (pid 668) from /
       fix: macOS AirPlay Receiver — System Settings → General → AirDrop & Handoff
[high] collision — port 6100 is claimed by 2 projects: memo-board, notes-api
       fix: give all but one of them a free port
[medium] drift — chronicle: registry says 6041 but code says 6040 (chronicle/config.py:4)
       fix: update the registry, or the code
[low] orphan — port 8188 is held by python3 (pid 68736) from ~/code/vendor-tool and is not registered
       fix: register it, or leave it alone
```

Checks: **collision** (two projects, one port), **squatter** (someone else holds a
registered port), **drift** (registry disagrees with the code), **missing-path**,
**orphan** (listening but unregistered), **unregistered** (`--scan ROOT`), and
**stale** (`--stale`: no commits for 180 days and not running).

`doctor` exits **1** when anything is `high`, so it works as a pre-flight check in a
script or CI job. `--json` gives the same findings as data.

### Map one service, or all of them

```console
$ portdeck map api-gateway
api-gateway  :4400
/home/you/code/api-gateway

ENTRYPOINTS
  app.py  (python)

ENDPOINTS
  GET    /api/health       app.py
  POST   /api/notify       routes/notify.py

OUTBOUND
  127.0.0.1:6040/api/events  → chronicle
  localhost:1234/v1          (unregistered)

LAYERS
  routes  (11 files)
  lib  (4 files)

scanned 34 files
```

```console
$ portdeck graph --mermaid
flowchart LR
  n_web_frontend["web-frontend<br/>:3000"]
  n_api_gateway["api-gateway<br/>:4400"]
  n_chronicle["chronicle<br/>:6040"]
  n_web_frontend -->|:4400| n_api_gateway
  n_api_gateway -->|:6040| n_chronicle
```

Both are static scans: routes are read out of Flask/FastAPI decorators, Express
handlers and Next.js file conventions, and every `http://host:port` literal is matched
back to a registered project. Nothing is imported or executed.

### Free a port

```console
$ portdeck who 5000
registered to daily-news
held by ControlCenter (pid 668) in /
  macOS AirPlay Receiver — System Settings → General → AirDrop & Handoff
```

portdeck never kills anything; it tells you what you are about to kill.

## How ports are discovered

Evidence is ranked, strongest first. The strongest kind present wins; ties go to the
most-cited port.

| Kind | Example |
|---|---|
| `compose` | `- "8081:80"` in a compose file |
| `listen` | `app.listen(3000)`, `app.run(port=4400)`, `uvicorn.run(..., port=8000)` |
| `config` | `"port": 5074` in `config.json` |
| `script` | `vite --port 5173`, `python3 -m http.server 6070` in npm scripts |
| `env` | `PORT=5123` in `.env` |
| `const` | `PORT: int = 6040`, `process.env.PORT \|\| 3000` |

Ports found in tests, fixtures and example directories are set aside — those servers
are real but temporary — and only used when a project offers nothing else, in which
case `scan` says so in the evidence column.

Measured against a hand-maintained 90-project registry (the tool's original purpose):
**61 of 66 projects resolved to the registered port**, 3 of the mismatches turned out
to be genuine registry drift the author had not noticed, and 2 projects declare their
port nowhere in the repository. Discovery is a starting point you confirm, not an
oracle: nothing is written without `--write`.

## The registry file

Plain JSON, resolved in this order: `$PORTDECK_REGISTRY`, `./portdeck.json`,
`~/.config/portdeck/registry.json`. Commit the local file to share a team's port map.

```json
{
  "version": 1,
  "projects": [
    { "name": "api-gateway", "port": 4400, "path": "~/code/api-gateway" }
  ]
}
```

A bare `[{...}]` list is also accepted on load, so an existing hand-rolled `ports.json`
works as-is. Paths under `$HOME` are stored as `~/...`. One malformed record never
takes down the rest of the file.

## Limits

- TCP only, IPv4 loopback for the reachability probe. UDP is out of scope.
- Process ownership needs `lsof`; without it `ls` still shows running/stopped but not
  who holds the port, and the `squatter` check cannot fire.
- Route and call detection is regex over source, capped at 1200 files per project. It
  finds conventional Flask/FastAPI/Express/Next.js shapes, not dynamically built ones.
- Everything is read-only. portdeck edits its own registry and nothing else.

## Development

```bash
python -m unittest discover -s tests -t .    # 102 tests, no dependencies
```

## License

MIT — see [LICENSE](LICENSE). Security policy: [SECURITY.md](SECURITY.md).
