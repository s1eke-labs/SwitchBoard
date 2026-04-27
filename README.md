# SwitchBoard

Local dashboard for Codex accounts, sessions, and usage.

[简体中文](README.zh-CN.md)

SwitchBoard is a small full-stack app for people who use Codex locally and want a clearer view of their account state, recent work, and token usage. It reads local Codex files from `CODEX_HOME`, stores SwitchBoard-only metadata in SQLite, and serves a React dashboard through a FastAPI backend.

## Features

- View local Codex accounts and the currently active account.
- Scan account profile and rate-limit snapshots from the ChatGPT backend.
- Switch the local Codex account by updating `CODEX_HOME/auth.json`.
- Rename or hide accounts inside SwitchBoard without changing Codex credentials.
- Export and import local account preferences for moving SwitchBoard setup between machines.
- Browse Codex sessions, search by text, and inspect session events.
- Review request logs, token usage, cache usage, and estimated costs.
- Run as separate backend/frontend dev servers, a production-style local app, or Docker Compose.

## Preview

![SwitchBoard dashboard](docs/images/dashbord.png)

## Requirements

- Python 3.13 and `uv` for the backend.
- Node.js and npm for the frontend.
- A local Codex home directory, usually `~/.codex`.

## Quick Start

For day-to-day development, run the backend and frontend in two terminals.

Terminal 1, start the backend API:

```bash
cd backend
APP_PASSWORD=switchboard \
CODEX_HOME="$HOME/.codex" \
SWITCHBOARD_DB=/tmp/switchboard-dev.sqlite \
uv run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

Terminal 2, start the frontend dev server:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the frontend terminal, usually `http://127.0.0.1:5173`, and sign in with the `APP_PASSWORD` value.

In this mode:

- Vite hot-reloads frontend changes.
- Uvicorn `--reload` restarts the backend when Python files change.
- Vite proxies `/api` requests to `http://127.0.0.1:8080`.

## Configuration

The backend reads configuration from environment variables. It also loads a `.env` file from the backend process working directory when present.

| Variable | Required | Description |
| --- | --- | --- |
| `APP_PASSWORD` | Yes | Password used to sign in to SwitchBoard. |
| `CODEX_HOME` | No | Codex home directory. Defaults to `/host-codex` in Docker-like environments when present, otherwise `~/.codex`. It must exist at startup. |
| `SWITCHBOARD_DB` | No | SQLite database path. Defaults to `/data/switchboard.sqlite` when `/data` exists, otherwise `backend/data/switchboard.sqlite` when run from `backend/`. |
| `SWITCHBOARD_STATIC_DIR` | No | Built frontend directory served by the backend, usually `frontend/dist`. |
| `SWITCHBOARD_COOKIE_SECURE` | No | Controls the session cookie `Secure` flag. Defaults to `false` for local HTTP development; set it to `true` behind HTTPS. |
| `CHATGPT_BACKEND_BASE` | No | ChatGPT backend base URL used when scanning account limits. Defaults to `https://chatgpt.com/backend-api`. |

For local development, `/tmp/switchboard-dev.sqlite` is a convenient disposable database path.

If `CODEX_HOME` is missing or points to a file instead of a directory, SwitchBoard fails fast during startup with a clear error.

## Development Commands

Run backend commands from `backend/`:

```bash
uv run pytest
APP_PASSWORD=switchboard CODEX_HOME="$HOME/.codex" SWITCHBOARD_DB=/tmp/switchboard-dev.sqlite uv run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

Run frontend commands from `frontend/`:

```bash
npm install
npm run dev
npm run lint
npm run build
npm run preview
```

`npm run lint` runs TypeScript checks. `npm run build` creates `frontend/dist`.

## Production-Style Local Run

Build the frontend:

```bash
cd frontend
npm install
npm run build
```

Then serve the API and built frontend from the backend:

```bash
cd ../backend
APP_PASSWORD=switchboard \
CODEX_HOME="$HOME/.codex" \
SWITCHBOARD_DB=/tmp/switchboard-dev.sqlite \
SWITCHBOARD_STATIC_DIR="$PWD/../frontend/dist" \
uv run uvicorn main:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` and sign in with `APP_PASSWORD`.

## Config Import and Export

Use the import and export buttons in the Accounts toolbar to move SwitchBoard-local account preferences between installs.

The exported JSON includes account IDs, generated display names, custom names, and hidden status. It does not include ChatGPT tokens, `auth.json`, sessions, usage data, scan history, SQLite caches, or `.env` values.

Importing a config file merges by `account_id`: accounts in the file update local custom names and hidden status, unknown accounts are created as placeholders, and local accounts missing from the file are left unchanged. The current Codex account is never imported as hidden.

## Docker Compose

Create `.env` in the repository root:

```bash
APP_PASSWORD=change-me
HOST_CODEX_HOME=/home/you/.codex
```

Then run:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8080` unless you set a different `PORT`.

The Codex directory is mounted read-only at `/host-codex`. SwitchBoard stores its SQLite data in the `switchboard_data` volume.

Because the default Compose mount is read-only, Docker mode is best for viewing accounts, sessions, and usage. Account switching requires write access to `CODEX_HOME/auth.json`; use the local backend command above or change the mount deliberately if you want switching inside the container.

## Repository Layout

```text
backend/
  main.py            FastAPI app and API routes
  accounts.py        Codex account scanning and switching
  sessions.py        Codex session reading
  usage.py           Usage aggregation and request logs
  db.py              SQLite setup and helpers
  security.py        Login cookie helpers
  tests/             Backend tests

frontend/
  src/App.tsx        Main React app
  src/app/           App shell and routing
  src/pages/         Dashboard, sessions, and request log pages
  src/features/      Account, session, and usage UI
  src/lib/           Shared client helpers
  src/components/ui/ UI primitives
  dist/              Built frontend output
```

## Security Notes

- SwitchBoard reads `auth.json` and local Codex session/state files from `CODEX_HOME`.
- ChatGPT tokens are not stored in SwitchBoard's SQLite database.
- Account switching rewrites the local Codex `auth.json`; restart Codex for the change to take effect.
- Hidden accounts and custom names are SwitchBoard-local metadata.
- Config export includes only SwitchBoard-local account preferences and never includes credentials.
- Do not commit `.env`, SQLite databases, or local Codex credentials.
- Usage cost estimates use a local pricing table for known model names; unknown model costs remain null.

## License

MIT
