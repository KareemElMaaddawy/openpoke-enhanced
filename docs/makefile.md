# Makefile Commands

The [Makefile](../Makefile) at the repo root wraps the quickstart steps and day-to-day operations. Run `make` (or `make help`) to list the targets.

It requires macOS or Linux, since it uses bash and `trap`. On Windows, follow the manual steps in the top-level [README](../README.md).

## First-time setup

```bash
make setup
```

This runs three steps:
1. Copies `.env.example` to `.env`. An existing `.env` is never overwritten.
2. Creates `.venv` with the first Python 3.10+ interpreter on your `PATH`. To use a specific one, pass `PYTHON=/path/to/python`.
3. Runs `make install`.

Then fill in your API keys in `.env` and confirm them:

```bash
make check-env
```

`check-env` checks `OPENROUTER_API_KEY`, `COMPOSIO_API_KEY` and `COMPOSIO_GMAIL_AUTH_CONFIG_ID`, in your shell environment first and then in `.env`. It fails if any key is missing or still set to its `your_..._here` placeholder.

## Installing dependencies

```bash
make install
```

Installs backend dependencies with `pip install -r server/requirements.txt` and frontend dependencies with `npm ci --prefix web`. Each step reruns only when `server/requirements.txt` or `web/package-lock.json` has changed since the last install, so running it again is cheap. `npm ci` installs exactly what the lockfile pins and never modifies it.

`dev` and `start` run `install` first, so you rarely need to call it directly.

## Running the app

| Command | What it does |
|---|---|
| `make dev` | Runs the API server with auto-reload and the Next.js app together in one terminal. Ctrl-C stops both. |
| `make web` | Runs only the Next.js web UI in the foreground, pointed at the API server on `API_PORT`. Pair it with `make start`. Ctrl-C stops it. |
| `make start` | Starts the API server in the background, logging to `.server.log` and recording its process ID in `.server.pid`. Does nothing if it's already running. |
| `make stop` | Stops the background API server. |
| `make logs` | Follows `.server.log`. |
| `make health` | Calls `GET /api/v1/health` on the API server and fails if it doesn't respond. |

The web app runs at <http://localhost:3000>. If that port is taken, Next.js moves to the next free one (3001, 3002, …) and prints the address it chose.

A common workflow is to keep the API in the background and the UI in a terminal:

```bash
make start
make web
```

### Choosing the routing mode

`ROUTING` picks how the interaction agent routes work to execution agents. It's passed to the server as `--routing`, and works with `make dev` and `make start`:

```bash
make dev ROUTING=records
```

| `ROUTING` | What runs |
|---|---|
| unset | `OPENPOKE_ROUTING` from your environment or `.env`, else `legacy` |
| `legacy` | Today's system: a names-only roster, and `send_message_to_agent(agent_name, ...)` creates or reuses by name |
| `records` | Agent records with IDs and purposes, routing by `agent_id`, and retrieval of at most K agents once the roster is large. See the [records and retrieval spec](agent-overload-records-retrieval-spec.md) |

In `records` mode the roster is shown in full up to 25 active agents and retrieved above that. To see retrieval with only a few agents, lower the threshold with `OPENPOKE_FULL_ROSTER_MAX` (an integer of 0 or more; `0` always retrieves):

```bash
OPENPOKE_FULL_ROSTER_MAX=3 make dev ROUTING=records
```

The server logs the mode in effect at startup, for example `Routing mode: records (embeddings openai/text-embedding-3-small@512, K=8, full_roster_max=3)`, and in `records` mode one `Routing candidates: ...` line per interaction-agent turn. `make start` writes these to `.server.log` (follow it with `make logs`); `make dev` prints them in the terminal. `GET /api/v1/meta` also reports `routing_mode`.

`make start` does nothing if the server is already running, so run `make stop` before switching modes.

### Choosing the API port

The API port is `API_PORT`. It defaults to `OPENPOKE_PORT` from your environment or `.env`, and then to `8001`, matching `server/config.py`. Override it per command:

```bash
make dev API_PORT=9000
make health API_PORT=9000
```

`make dev` and `make web` also point the web app at that port by setting `PY_SERVER_URL`, unless you've already set `PY_SERVER_URL` yourself.

The variable is named `API_PORT` rather than `PORT` because Next.js binds to `PORT` when it's set, which would put the web app on the API's port.

## Cleaning up

```bash
make clean
```

Removes `__pycache__` directories, the Next.js build output in `web/.next`, and the background server's `.server.log` and `.server.pid`. It leaves `.venv`, `web/node_modules`, `.env` and the runtime data in `server/data/` alone.
