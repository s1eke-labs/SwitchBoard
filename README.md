# SwitchBoard

Local dashboard for Codex accounts, sessions, and usage.

SwitchBoard is a small full-stack app:

- Backend: FastAPI, SQLite, and local Codex account/session readers.
- Frontend: React, Vite, TypeScript, and Tailwind CSS.

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

The backend reads configuration from environment variables.

| Variable | Required | Description |
| --- | --- | --- |
| `APP_PASSWORD` | Yes | Password used to sign in to SwitchBoard. |
| `CODEX_HOME` | Yes | Codex home directory. It must exist at startup, and SwitchBoard reads `auth.json` from here. |
| `SWITCHBOARD_DB` | No | SQLite database path. Defaults to local app behavior if omitted. |
| `SWITCHBOARD_STATIC_DIR` | No | Built frontend directory served by the backend, usually `frontend/dist`. |
| `SWITCHBOARD_COOKIE_SECURE` | No | Controls the session cookie `Secure` flag. Defaults to `false` for local HTTP development; set it to `true` behind HTTPS. |

For local development, `/tmp/switchboard-dev.sqlite` is a convenient disposable database path.

If `CODEX_HOME` is missing or points to a file instead of a directory, SwitchBoard now fails fast during startup with a clear error.

## Development Commands

Run backend tests from `backend/`:

```bash
uv run pytest
```

Run frontend checks from `frontend/`:

```bash
npm run lint
npm run build
```

Use `npm run dev` for frontend development and `npm run preview` to serve the built frontend locally.

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

The Codex directory is mounted read-only at `/host-codex`. SwitchBoard stores its SQLite data in the `switchboard_data` volume.

## Repository Layout

```text
backend/
  main.py            FastAPI app
  accounts.py        Codex account scanning
  sessions.py        Codex session reading
  usage.py           Usage aggregation
  tests/             Backend tests

frontend/
  src/App.tsx        Main React app
  src/lib/           Shared client helpers
  src/components/ui/ UI primitives
  dist/              Built frontend output
```

## Security Notes

- SwitchBoard reads only `auth.json` from `CODEX_HOME`.
- ChatGPT tokens are never stored in SwitchBoard.
- Hidden accounts are hidden only in SwitchBoard's SQLite database.
- Do not commit `.env`, SQLite databases, or local Codex credentials.
- Usage cost estimates use the OpenAI API pricing table for known model names; unknown model costs remain null.
