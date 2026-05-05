<div align="center">
  <div>
    <img src="./docs/images/switchboard-logo-source.png" alt="SwitchBoard" width="116">
  </div>

  <h1 style="margin-top: 10px;">SwitchBoard</h1>

  <h2>Local command center for Codex accounts, sessions, usage, and image jobs.</h2>

  <div align="center">
    <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
    <img alt="Python" src="https://img.shields.io/badge/python-3.13+-blue">
    <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688">
    <img alt="React" src="https://img.shields.io/badge/frontend-React%2019-61dafb">
    <img alt="Docker" src="https://img.shields.io/badge/docker-compose-2496ed">
  </div>

  <p>
    <a href="#latest-news">Latest News</a>
    ◆ <a href="#why-switchboard">Why SwitchBoard?</a>
    ◆ <a href="#quick-start">Quick Start</a>
    ◆ <a href="#demo">Demo</a>
    ◆ <a href="#installation">Installation</a>
    ◆ <a href="#documentation">Documentation</a>
  </p>

  <p><a href="./README.zh-CN.md">简体中文</a></p>
</div>

## Latest News

- **[2026/05]** Refactored the Images page into focused feature modules and local HeroUI-backed components.
- **[2026/05]** Improved queued image generation and task settings.
- **[2026/05]** Added a paginated image gallery, per-image and per-job deletion, and responsive gallery page sizing.
- **[2026/05]** Unified persistent data configuration under `SWITCHBOARD_DATA_DIR`.

## Why SwitchBoard?

SwitchBoard gives local Codex users a protected dashboard for the operational details that are otherwise scattered across `CODEX_HOME`: active account state, saved credentials, session history, request logs, token usage, cost estimates, and queued image generation work.

- **Account control** - See known Codex accounts, scan current account limits, rename or hide accounts locally, and switch accounts by replacing `CODEX_HOME/auth.json`.
- **Session visibility** - Browse Codex sessions, search by text, inspect compact event previews, and open raw event details when needed.
- **Usage and cost review** - Aggregate request logs by account, model, cache usage, token class, and estimated USD cost.
- **Image job workspace** - Queue text-to-image and reference-image jobs, browse generated outputs in a paginated gallery, retry jobs, download images, and delete unwanted results.
- **Local-first security** - Keep ChatGPT tokens out of SQLite, protect the web UI with an app password, and store saved account credentials in a private auth vault.

## Quick Start

Run the backend and frontend in two terminals for local use.

```bash
# 1. Start the backend API
cd backend
APP_PASSWORD=switchboard \
CODEX_HOME="$HOME/.codex" \
SWITCHBOARD_DATA_DIR=./data/dev \
uv run uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

```bash
# 2. Start the frontend dev server
cd frontend
npm install
npm run dev
```

Open the Vite URL shown in the frontend terminal, usually `http://127.0.0.1:5173`, and sign in with the `APP_PASSWORD` value.

> **Prerequisites**: Python 3.13 with `uv`, Node.js with npm, and a local Codex home directory such as `~/.codex`.
>
> **Need one-command local packaging?** Use [Docker Compose](#docker-compose), or build the frontend and serve it from FastAPI with [Production-Style Local Run](#production-style-local-run).

## Demo

### Dashboard Preview

<div align="center">
  <img src="./docs/images/dashbord.png" alt="SwitchBoard dashboard" width="780">
</div>

### Typical Workflow

```text
Codex local files
  -> SwitchBoard scans accounts, sessions, and usage logs
  -> FastAPI serves authenticated APIs and the React app
  -> Browser dashboard shows accounts, usage, sessions, request logs, and images
```

What you can do from the UI:

- Scan the current Codex account and inspect 5-hour and weekly remaining quota.
- Switch to a saved account while preserving the existing `auth.json` file owner and private permissions.
- Search sessions, open event previews, and jump through paginated history.
- Filter request logs by account or unassigned bucket and review token/cost summaries.
- Create image jobs with aspect ratio, quality, count, and up to 4 reference images.

## Installation

This section covers detailed setup options. For the fastest local start, use [Quick Start](#quick-start).

### Environment Setup

Backend dependencies are managed by `uv` from `backend/`:

```bash
cd backend
uv sync
```

Frontend dependencies are managed by npm from `frontend/`:

```bash
cd frontend
npm install
```

### Configuration

The backend reads environment variables and also loads a `.env` file from the backend process working directory when present.

| Variable | Required | Description |
| --- | --- | --- |
| `APP_PASSWORD` | Yes | Password used to sign in to SwitchBoard. |
| `CODEX_HOME` | No | Codex home directory. Defaults to `/host-codex` when that Docker-style mount exists, otherwise `~/.codex`. The directory must exist at startup. |
| `SWITCHBOARD_DATA_DIR` | No | Persistent SwitchBoard data directory. Defaults to `/data` when present, otherwise `data` under the backend working directory. Stores `switchboard.sqlite`, `auth-vault/`, and `images/`. |
| `SWITCHBOARD_STATIC_DIR` | No | Built frontend directory served by FastAPI, usually `frontend/dist`. |
| `SWITCHBOARD_COOKIE_SECURE` | No | Controls the session cookie `Secure` flag. Defaults to `false` for local HTTP; set `true` behind HTTPS. |
| `CHATGPT_BACKEND_BASE` | No | ChatGPT backend base URL used for account scans and image proxy calls. Defaults to `https://chatgpt.com/backend-api`. |
| `SWITCHBOARD_IMAGE_MODEL` | No | Default image model. Defaults to `gpt-image-2`. |
| `SWITCHBOARD_IMAGE_RESPONSES_MODEL` | No | Responses API host model used to invoke image generation. Defaults to `gpt-5.4-mini`. |
| `SWITCHBOARD_IMAGE_RESPONSES_PATH` | No | Path or full URL for image Responses calls. Defaults to `/codex/responses`. |
| `SWITCHBOARD_IMAGE_TIMEOUT_SECONDS` | No | Image generation timeout. Defaults to `300`. |
| `SWITCHBOARD_IMAGE_MAX_PROMPT_CHARS` | No | Maximum accepted prompt length. Defaults to `4000`. |
| `SWITCHBOARD_IMAGE_CONCURRENCY` | No | Maximum number of single-image jobs running at once. Defaults to `2`; set `1` for serial generation. |
| `SWITCHBOARD_IMAGE_DEBUG` | No | Enables image request/response debug logging. Defaults to `false`; tokens and image base64 payloads are still not logged. |

Root-level `.env.example` is intended for Docker Compose:

```bash
APP_PASSWORD=change-me
CODEX_HOME=~/.codex
DATA_DIR=./backend/data
CHATGPT_BACKEND_BASE=https://chatgpt.com/backend-api
```

> **Security Note**: Do not commit `.env`, SQLite databases, local Codex credentials, or generated private data. Legacy path variables `SWITCHBOARD_DB`, `SWITCHBOARD_AUTH_VAULT`, and `SWITCHBOARD_IMAGE_OUTPUT_DIR` have been removed; use `SWITCHBOARD_DATA_DIR`.

## Images

Open the Images page after signing in. SwitchBoard uses the current `CODEX_HOME/auth.json` ChatGPT access token in memory, so no image-specific key is configured in SwitchBoard or sent to the browser.

Typical workflow:

1. Enter a prompt, then choose aspect ratio, quality tier, and image count.
2. Optionally attach up to 4 PNG, JPEG, or WebP reference images, each up to 10 MB.
3. Submit the job. SwitchBoard queues it, polls for progress, and shows a toast when it finishes or fails.
4. Browse results in the gallery. Pages are counted by image tile, and page size adapts to the gallery viewport.
5. Preview, download, stop active jobs, retry failed jobs, delete individual outputs, or delete a whole job.

Notes:

- The gallery shows generated images, and files are stored under `SWITCHBOARD_DATA_DIR/images/YYYY/MM/DD/{job_id}/`.
- Image job metadata is stored in `SWITCHBOARD_DATA_DIR/switchboard.sqlite`; ChatGPT tokens are not stored there.
- Advanced image job, API, and integration details live in [docs/image-jobs.md](./docs/image-jobs.md).

## Production-Style Local Run

Build the frontend:

```bash
cd frontend
npm install
npm run build
```

Then serve both API and built frontend from FastAPI:

```bash
cd ../backend
APP_PASSWORD=switchboard \
CODEX_HOME="$HOME/.codex" \
SWITCHBOARD_DATA_DIR=./data/dev \
SWITCHBOARD_STATIC_DIR="$PWD/../frontend/dist" \
uv run uvicorn main:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` and sign in with `APP_PASSWORD`.

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

Compose uses `.env` for interpolation. The host Codex directory is mounted read-write at `/host-codex`, and the host SwitchBoard data directory is mounted at `/data`. The container fixes `CODEX_HOME=/host-codex`, `SWITCHBOARD_DATA_DIR=/data`, and serves the built frontend from `/app/frontend/dist`.

The container process may run as root, but SwitchBoard preserves the existing owner and group of `CODEX_HOME/auth.json` when replacing it. If the Codex mount is read-only, Docker mode is limited to viewing accounts, sessions, usage, and image history that does not require writing credentials.

## Config Import and Export

Use the import and export buttons in the Accounts toolbar to move SwitchBoard-local account display state between installs.

The exported JSON includes account IDs, generated display names, custom names, hidden status, user and plan labels, expired status, last scan time, 5-hour remaining, weekly remaining, and reset times. It does not include ChatGPT tokens, `auth.json`, sessions, request logs, SQLite usage caches, image files, or `.env` values.

Import merges by `account_id`: accounts in the file update local display metadata and latest rate-limit snapshots, unknown accounts are created as placeholders, and local accounts missing from the file are left unchanged. The current Codex account is never imported as hidden, and importing a `current` marker never switches the active Codex account.

## Documentation

- [docs/development.md](./docs/development.md) - Development commands, architecture, repository layout, and contribution notes.
- [docs/image-jobs.md](./docs/image-jobs.md) - Image job API and task-dispatcher integration details.

## Security Notes

- SwitchBoard reads `auth.json` plus local Codex session and state files from `CODEX_HOME`.
- ChatGPT tokens are not stored in SwitchBoard's SQLite database.
- Saved account credentials live in `SWITCHBOARD_DATA_DIR/auth-vault` as private `auth.json` files, not under `CODEX_HOME` by default.
- Account switching rewrites local `CODEX_HOME/auth.json`; restart Codex for the change to take effect.
- Docker account switching preserves the existing `auth.json` owner/group and writes the file with `0600` permissions.
- Hidden accounts and custom names are SwitchBoard-local metadata.
- Config export includes only SwitchBoard-local account display state and never includes credentials.
- Image generation reads the current access token only in memory; tokens are never returned to the frontend.
- Task dispatcher tokens are encrypted in the private auth vault and are returned to the frontend only as masked summaries.
- Image debug logging and stored upstream metadata never include the access token, Authorization header value, image base64 payloads, safety identifiers, or prompt cache keys.
- Do not commit `.env`, SQLite databases, generated private data, or local Codex credentials.
- Usage cost estimates use a local pricing table for known model names; unknown model costs remain null.

## License

SwitchBoard is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

## Acknowledgments

SwitchBoard exists for people running Codex locally who want a clearer, safer, and more inspectable workspace around their accounts and usage.
