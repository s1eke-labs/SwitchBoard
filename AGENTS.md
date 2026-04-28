# Agent Notes

Use `README.md` for project overview, setup, commands, Docker behavior, configuration, and repository layout. Keep both README files in sync when changing user-facing behavior, setup, configuration, or security notes.

## Implementation Preferences

Backend code follows the existing flat FastAPI module style in `backend/`. Use typed public helpers and keep behavior tests focused around the module being changed.

Frontend code uses React, Vite, Tailwind CSS, and shadcn/ui primitives. Prefer existing `frontend/src/components/ui` primitives, add missing shadcn primitives from `frontend/` with `npm run ui -- add <component>`, and keep SwitchBoard-specific composition in `frontend/src/features` or `frontend/src/pages`. Use Sonner toasts for transient status messages.

## Validation

When changing account scanning, session parsing, request-log aggregation, pricing, authentication, or configuration behavior, add or update focused backend tests.

When changing visible frontend behavior, run `npm run lint` from `frontend/`.

## Commit Messages

Use Conventional Commits for commit messages: `<type>(<scope>): <summary>`. Write the summary in Chinese unless the surrounding change is already English-only. 

## Security Notes

SwitchBoard reads `auth.json` plus local Codex session/state files from `CODEX_HOME`. Account switching rewrites `CODEX_HOME/auth.json`, so preserve user credentials carefully and never log token values. ChatGPT tokens must not be stored in SwitchBoard's SQLite database. Hidden accounts and custom account names are SwitchBoard-local metadata.

## AI Agent Guidelines
**Use Chinese**: The AI must use Chinese for all outputs (including but not limited to conversations, explanations, planning, code comments, etc.).
