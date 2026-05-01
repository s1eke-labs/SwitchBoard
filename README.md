# SwitchBoard

Local dashboard for Codex accounts, sessions, and usage.

[简体中文](README.zh-CN.md)

SwitchBoard is a small full-stack app for people who use Codex locally and want a clearer view of their account state, recent work, and token usage. It reads local Codex files from `CODEX_HOME`, stores SwitchBoard-only metadata in SQLite, keeps saved account credentials in a private SwitchBoard auth vault, and serves a React dashboard through a FastAPI backend.

## Features

- View local Codex accounts, the currently active account, and the elapsed time since each account was added to SwitchBoard.
- Scan account profile and rate-limit snapshots from the ChatGPT backend.
- Switch the local Codex account by updating `CODEX_HOME/auth.json`.
- Rename or hide accounts inside SwitchBoard without changing Codex credentials.
- Export and import local account display state for moving SwitchBoard setup between machines.
- Browse Codex sessions, search by text, and inspect session events.
- Review request logs, token usage, cache usage, estimated costs, and account attribution filters.
- Queue text-to-image and reference-image generation jobs from a protected local WebUI, organize them into persistent image sessions, and proxy them to an OpenAI Images-compatible upstream.
- Default the interface to English or Simplified Chinese based on browser language, with manual switching available on the login page and app header.
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
SWITCHBOARD_DATA_DIR=./data/dev \
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
| `SWITCHBOARD_DATA_DIR` | No | Persistent SwitchBoard data directory. Defaults to `/data` when it exists, otherwise `backend/data` when run from `backend/`. SwitchBoard stores `switchboard.sqlite`, `auth-vault/`, and `images/` under this directory. |
| `SWITCHBOARD_STATIC_DIR` | No | Built frontend directory served by the backend, usually `frontend/dist`. |
| `SWITCHBOARD_COOKIE_SECURE` | No | Controls the session cookie `Secure` flag. Defaults to `false` for local HTTP development; set it to `true` behind HTTPS. |
| `CHATGPT_BACKEND_BASE` | No | ChatGPT backend base URL used when scanning account limits. Defaults to `https://chatgpt.com/backend-api`. |
| `SWITCHBOARD_IMAGE_MODEL` | No | Default image model. Defaults to `gpt-image-2`. |
| `SWITCHBOARD_IMAGE_RESPONSES_MODEL` | No | Responses API host model used to invoke the image generation tool. Defaults to `gpt-5.4-mini`. |
| `SWITCHBOARD_IMAGE_RESPONSES_PATH` | No | Path appended to `CHATGPT_BACKEND_BASE` for image Responses calls. Defaults to `/codex/responses`. Full URLs are also accepted. |
| `SWITCHBOARD_IMAGE_TIMEOUT_SECONDS` | No | Image generation timeout. Defaults to `300`. |
| `SWITCHBOARD_IMAGE_MAX_PROMPT_CHARS` | No | Maximum prompt length accepted by the backend. Defaults to `4000`. |
| `SWITCHBOARD_IMAGE_DEBUG` | No | Logs image request/response debugging details. Defaults to `false`; access tokens are still not logged. |

For local development, `SWITCHBOARD_DATA_DIR=./data/dev` is a convenient disposable data directory.

If `CODEX_HOME` is missing or points to a file instead of a directory, SwitchBoard fails fast during startup with a clear error.

The Images page uses the current `CODEX_HOME/auth.json` ChatGPT access token and calls the Responses upstream directly from the backend. The page submits jobs to a persisted FIFO queue, then polls for completion so the browser is not held open on the long upstream request. Completed and failed jobs trigger in-app toast notifications while SwitchBoard remains open.

Image jobs are grouped into persistent image sessions. The Images page shows a paginated session list, lets you create or permanently delete sessions, and renders the selected session as a chat-like stream of compact image thumbnails. Click a thumbnail to open the full preview with its prompt, revised prompt, references, and download action. Existing image jobs from older SwitchBoard databases are migrated into an "Image history" session. Sessions with queued or running jobs cannot be deleted until those jobs finish.

Image sessions are SwitchBoard-local history groups. Image generation requests use `store: false` for upstream compatibility and privacy, so queued jobs are not automatically chained through upstream `previous_response_id`; follow-up prompts should include the needed context or reference images. If an upstream response ID is returned, SwitchBoard may keep it as local job metadata, while ChatGPT access tokens are still never stored.

Image jobs can include up to 4 reference images. Use the plus button above the prompt to upload references in the same fixed-height prompt composer; thumbnail slots stay reserved, and clicking a pending thumbnail opens a local preview before submission. Each reference must be PNG, JPEG, or WebP and no larger than 10 MB. References are saved alongside the job so task history can be reopened after restarting SwitchBoard.

The browser-facing queue endpoints are:

```text
POST /api/images/conversations
GET /api/images/conversations?page=1&limit=4
GET /api/images/conversations/{conversation_id}/jobs
DELETE /api/images/conversations/{conversation_id}
POST /api/images/jobs
GET /api/images/jobs
GET /api/images/jobs/{job_id}
```

For direct synchronous integrations, the original generation endpoint remains available:

```text
POST /api/images/generations
```

Open the Images page from the app header after signing in. No image-specific upstream key is stored or sent to the browser.

Generated images and saved reference images are stored under `SWITCHBOARD_DATA_DIR/images` and served back through authenticated `/api/images/files/{filename}` URLs. Image session metadata, queue job status, reference metadata, returned upstream response IDs, results, and errors are stored in `SWITCHBOARD_DATA_DIR/switchboard.sqlite`. Deleting an image session removes its SQLite history plus referenced generated and reference image files. If SwitchBoard restarts while a job is running, that job is restored to queued state.

## Development Commands

Run backend commands from `backend/`:

```bash
uv run pylint --rcfile=.pylintrc .
uv run pytest
APP_PASSWORD=switchboard CODEX_HOME="$HOME/.codex" SWITCHBOARD_DATA_DIR=./data/dev uv run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

Run frontend commands from `frontend/`:

```bash
npm install
npm run dev
npm run lint
npm run build
npm run preview
```

`uv run pylint --rcfile=.pylintrc .` runs backend lint checks. `npm run lint` runs frontend ESLint and TypeScript checks. `npm run build` creates `frontend/dist`.

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
SWITCHBOARD_DATA_DIR=./data/dev \
SWITCHBOARD_STATIC_DIR="$PWD/../frontend/dist" \
uv run uvicorn main:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` and sign in with `APP_PASSWORD`.

## Config Import and Export

Use the import and export buttons in the Accounts toolbar to move SwitchBoard-local account display state between installs.

The exported JSON includes account IDs, generated display names, custom names, hidden status, user and plan labels, expired status, last scan time, 5h remaining, weekly remaining, and reset times. It does not include ChatGPT tokens, `auth.json`, sessions, request logs, SQLite usage caches, or `.env` values.

Importing a config file merges by `account_id`: accounts in the file update local display metadata and latest rate-limit snapshot, unknown accounts are created as placeholders, and local accounts missing from the file are left unchanged. The current Codex account is never imported as hidden, and importing a `current` marker never switches the active Codex account.

## Docker Compose

Create `.env` in the repository root:

```bash
APP_PASSWORD=change-me
CODEX_HOME=/home/you/.codex
DATA_DIR=./backend/data
```

Then run:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8080` unless you set a different `PORT`.

Compose reads these values from `.env` for interpolation only. `CODEX_HOME` is the host Codex directory mounted read-write into the container at `/host-codex`, and `DATA_DIR` is the host SwitchBoard data directory mounted into the container at `/data`. The container's internal `CODEX_HOME=/host-codex` and `SWITCHBOARD_DATA_DIR=/data` are fixed in the Docker image.

SwitchBoard stores `switchboard.sqlite`, private `auth-vault/`, and generated `images/` under `DATA_DIR` on the host.

The container process may run as root, but SwitchBoard preserves the existing owner and group of `CODEX_HOME/auth.json` when replacing it. Saved account credentials are written outside `CODEX_HOME` by default under the mounted data directory's `auth-vault/` with private directory and file permissions. If you change the Codex mount to read-only, Docker mode is limited to viewing accounts, sessions, and usage.

## Repository Layout

```text
backend/
  main.py            FastAPI app and API routes
  accounts.py        Codex account scanning and switching
  images.py          Image generation API proxy
  sessions.py        Codex session reading
  usage.py           Usage aggregation and request logs
  db.py              SQLite setup and helpers
  security.py        Login cookie helpers
  tests/             Backend tests

frontend/
  src/App.tsx        Main React app
  src/app/           App shell and routing
  src/pages/         Dashboard, sessions, request log, and image pages
  src/features/      Account, session, and usage UI
  src/lib/           Shared client helpers
  src/components/ui/ UI primitives
  dist/              Built frontend output
```

## Request Log Attribution

SwitchBoard records which Codex account is active when it observes the current `auth.json`, such as during account scans, account switching, and usage-log synchronization. Request logs can be filtered by account on the Request Logs page, and the summary cards on that page only count the selected account or unassigned bucket.

Existing usage events that were collected before account attribution was available remain unassigned. SwitchBoard does not guess historical ownership, and it does not store ChatGPT tokens in SQLite to support attribution.

## Security Notes

- SwitchBoard reads `auth.json` and local Codex session/state files from `CODEX_HOME`.
- ChatGPT tokens are not stored in SwitchBoard's SQLite database.
- Saved account credentials live in `SWITCHBOARD_DATA_DIR/auth-vault` as private `auth.json` files, not under `CODEX_HOME` by default.
- Account switching rewrites the local Codex `auth.json`; restart Codex for the change to take effect.
- Docker account switching preserves the existing `auth.json` owner/group and writes the file with `0600` permissions.
- Hidden accounts and custom names are SwitchBoard-local metadata.
- Config export includes only SwitchBoard-local account display state and never includes credentials.
- Image generation reads the current `CODEX_HOME/auth.json` access token only in memory; tokens are never stored in SQLite or returned to the frontend.
- Image generation sends upstream requests with `store: false`; image sessions are local history groups and do not automatically retain upstream response state for follow-up prompts.
- Reference images are stored as private files for job history, but the browser sends them only to the authenticated SwitchBoard backend.
- Image debug logging never prints the access token, Authorization header value, or image base64 payloads.
- Do not commit `.env`, SQLite databases, or local Codex credentials.
- Usage cost estimates use a local pricing table for known model names; unknown model costs remain null.

## License

MIT
