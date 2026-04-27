# Repository Guidelines

## Project Structure & Module Organization

SwitchBoard is a small full-stack dashboard. Backend code lives in `backend/` as flat Python modules such as `main.py`, `accounts.py`, `sessions.py`, `usage.py`, `db.py`, and `security.py`. Backend tests are in `backend/tests/` and use `test_*.py` naming.

Frontend code lives in `frontend/`. Vite/React entry points are `frontend/src/main.tsx` and `frontend/src/App.tsx`; shared client helpers are in `frontend/src/lib/`; reusable UI primitives are in `frontend/src/components/ui/`. Build output is `frontend/dist/`.

## Build, Test, and Development Commands

Run backend commands from `backend/`:

```bash
uv run pytest
APP_PASSWORD=switchboard CODEX_HOME="$HOME/.codex" SWITCHBOARD_DB=/tmp/switchboard-dev.sqlite SWITCHBOARD_STATIC_DIR="$PWD/../frontend/dist" uv run uvicorn main:app --host 127.0.0.1 --port 8080
```

`uv run pytest` runs the FastAPI/unit tests. The `uvicorn` command starts the app with a temporary SQLite database.

Run frontend commands from `frontend/`:

```bash
npm install
npm run dev
npm run lint
npm run build
npm run preview
```

`npm run dev` starts Vite, `lint` runs TypeScript checks, `build` produces `dist/`, and `preview` serves the built frontend. Docker users can run `docker compose up --build` from the repo root after creating `.env`.

## Coding Style & Naming Conventions

Python targets 3.13 and follows module-level FastAPI patterns. Use 4-space indentation, typed public helpers, and snake_case for modules, functions, and variables. Keep tests close to behavior.

TypeScript uses React, Vite, Tailwind CSS, and small UI primitives. Use PascalCase for components, camelCase for functions and variables, and keep shared API/client logic in `frontend/src/lib/`. Prefer existing `components/ui` primitives.

## Versioning & Compatibility

While the project version is `0.1.0`, treat SwitchBoard as an unpublished development build. Do not preserve backward compatibility for APIs, database schema, configuration, or UI behavior unless a task explicitly requires it.

## Testing Guidelines

Backend tests use `pytest` with `pytest-asyncio`; async tests are enabled by `pyproject.toml`. Add tests under `backend/tests/` with names like `test_accounts.py` and functions named `test_<behavior>`. For frontend changes, at minimum run `npm run lint`.

## Commit & Pull Request Guidelines

This repository currently has no committed history, so there is no existing commit convention to preserve. Use concise, imperative commit subjects such as `Add usage session tests` or `Fix account scan error handling`.

Pull requests should include a summary, verification commands, linked issues when applicable, and screenshots for visible UI changes. Note configuration changes involving `.env`, `CODEX_HOME`, `APP_PASSWORD`, or `SWITCHBOARD_DB`.

## Security & Configuration Tips

Do not commit `.env`, SQLite databases, or local Codex credentials. The app should only read `auth.json` from `CODEX_HOME`, and ChatGPT tokens should never be stored. Use `.env.example` and README examples as configuration references.
