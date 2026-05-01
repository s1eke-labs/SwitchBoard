FROM node:24-bookworm AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
ENV SWITCHBOARD_STATIC_DIR=/app/frontend/dist \
    CODEX_HOME=/host-codex \
    SWITCHBOARD_DATA_DIR=/data
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
