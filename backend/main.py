from __future__ import annotations

import asyncio
import hmac
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from accounts import AccountDTO, ScanResult, hide_account, list_accounts, scan_current_account, set_account_custom_name, switch_account
from config import get_settings, validate_runtime_settings
from config_transfer import ConfigExportDTO, ConfigImportSummary, export_config, import_config
from db import init_db
from security import clear_login_cookie, require_auth, set_login_cookie
from sessions import (
    SessionDetail,
    SessionEvent,
    SessionEventsResponse,
    SessionListResponse,
    SessionUserIndexResponse,
    get_session_detail,
    get_session_event,
    iso_to_ts,
    list_session_events,
    list_session_user_index,
    list_sessions,
)
from usage import (
    AGGREGATION_REFRESH_SECONDS,
    UsageAggregatesResponse,
    UsageEventsResponse,
    UsageRequestLogsResponse,
    get_usage_aggregates,
    get_usage_events,
    get_usage_request_logs,
)


logger = logging.getLogger(__name__)
ACCOUNT_REFRESH_SECONDS = 5 * 60


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    ok: bool


class AccountNameRequest(BaseModel):
    custom_name: str | None = None


def auth_dependency(request: Request) -> None:
    require_auth(request)


def _seconds_until_next_usage_aggregation() -> float:
    now = time.time()
    return max(1.0, AGGREGATION_REFRESH_SECONDS - (now % AGGREGATION_REFRESH_SECONDS))


async def refresh_current_account(settings, scan_lock: asyncio.Lock) -> None:
    try:
        async with scan_lock:
            await scan_current_account(settings)
    except Exception:
        logger.exception("Account refresh failed")


def create_app() -> FastAPI:
    settings = get_settings()
    validate_runtime_settings(settings)
    init_db(settings.db_path)
    account_scan_lock = asyncio.Lock()

    async def usage_aggregation_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(get_usage_aggregates, settings)
            except Exception:
                logger.exception("Usage aggregation failed")
            await asyncio.sleep(_seconds_until_next_usage_aggregation())

    async def account_refresh_loop() -> None:
        while True:
            await asyncio.sleep(ACCOUNT_REFRESH_SECONDS)
            await refresh_current_account(settings, account_scan_lock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        usage_task = asyncio.create_task(usage_aggregation_loop())
        account_task = asyncio.create_task(account_refresh_loop())
        app.state.usage_aggregation_task = usage_task
        app.state.account_refresh_task = account_task
        try:
            yield
        finally:
            usage_task.cancel()
            account_task.cancel()
            with suppress(asyncio.CancelledError):
                await usage_task
            with suppress(asyncio.CancelledError):
                await account_task

    app = FastAPI(title="SwitchBoard", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest, response: Response) -> LoginResponse:
        if not hmac.compare_digest(payload.password, settings.app_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
        set_login_cookie(response, settings)
        return LoginResponse(ok=True)

    @app.post("/api/auth/logout", response_model=LoginResponse)
    def logout(response: Response) -> LoginResponse:
        clear_login_cookie(response, settings)
        return LoginResponse(ok=True)

    authed = [Depends(auth_dependency)]

    @app.get("/api/accounts", response_model=list[AccountDTO], dependencies=authed)
    def accounts() -> list[AccountDTO]:
        return list_accounts(settings)

    @app.post("/api/accounts/scan", response_model=ScanResult, dependencies=authed)
    async def scan_account() -> ScanResult:
        try:
            async with account_scan_lock:
                return await scan_current_account(settings)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/accounts/{account_id}/switch", response_model=ScanResult, dependencies=authed)
    async def switch_current_account(account_id: str) -> ScanResult:
        try:
            async with account_scan_lock:
                return await switch_account(settings, account_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account auth not found") from exc
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/api/accounts/{account_id}/hide", response_model=dict[str, bool], dependencies=authed)
    def hide(account_id: str) -> dict[str, bool]:
        try:
            hide_account(settings, account_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found") from exc
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/name", response_model=AccountDTO, dependencies=authed)
    def rename_account(account_id: str, payload: AccountNameRequest) -> AccountDTO:
        try:
            return set_account_custom_name(settings, account_id, payload.custom_name)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found") from exc

    @app.get("/api/config/export", response_model=ConfigExportDTO, dependencies=authed)
    def export_switchboard_config() -> ConfigExportDTO:
        return export_config(settings)

    @app.post("/api/config/import", response_model=ConfigImportSummary, dependencies=authed)
    async def import_switchboard_config(request: Request) -> ConfigImportSummary:
        try:
            payload = await request.json()
            return import_config(settings, payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/sessions", response_model=SessionListResponse, dependencies=authed)
    def sessions(
        query: str | None = None,
        cwd: str | None = None,
        from_: Annotated[str | None, Query(alias="from")] = None,
        to: str | None = None,
        limit: int = 7,
        cursor: str | None = None,
        page: int = 1,
    ) -> SessionListResponse:
        try:
            return list_sessions(
                settings,
                query=query,
                cwd=cwd,
                from_ts=iso_to_ts(from_) if from_ else None,
                to_ts=iso_to_ts(to) if to else None,
                limit=limit,
                cursor=cursor,
                page=page,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/sessions/{thread_id}", response_model=SessionDetail, dependencies=authed)
    def session_detail(thread_id: str) -> SessionDetail:
        try:
            return get_session_detail(settings, thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from exc

    @app.get("/api/sessions/{thread_id}/events", response_model=SessionEventsResponse, dependencies=authed)
    def session_events(thread_id: str, cursor: str | None = None, limit: int = 100) -> SessionEventsResponse:
        try:
            return list_session_events(settings, thread_id, cursor=cursor, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from exc

    @app.get("/api/sessions/{thread_id}/user-index", response_model=SessionUserIndexResponse, dependencies=authed)
    def session_user_index(thread_id: str) -> SessionUserIndexResponse:
        try:
            return list_session_user_index(settings, thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found") from exc

    @app.get("/api/sessions/{thread_id}/events/{line_no}", response_model=SessionEvent, dependencies=authed)
    def session_event(thread_id: str, line_no: int) -> SessionEvent:
        try:
            return get_session_event(settings, thread_id, line_no)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session event not found") from exc

    @app.get("/api/usage/events", response_model=UsageEventsResponse, dependencies=authed)
    def usage_events(
        from_: Annotated[str | None, Query(alias="from")] = None,
        to: str | None = None,
    ) -> UsageEventsResponse:
        return get_usage_events(settings, from_, to)

    @app.get("/api/usage/aggregates", response_model=UsageAggregatesResponse, dependencies=authed)
    def usage_aggregates() -> UsageAggregatesResponse:
        return get_usage_aggregates(settings)

    @app.get("/api/usage/request-logs", response_model=UsageRequestLogsResponse, dependencies=authed)
    def usage_request_logs(
        from_: Annotated[str | None, Query(alias="from")] = None,
        to: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        page: int = 1,
    ) -> UsageRequestLogsResponse:
        try:
            return get_usage_request_logs(settings, from_value=from_, to_value=to, limit=limit, cursor=cursor, page=page)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    static_dir = settings.static_dir
    if static_dir and static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = static_dir / path
            if path and candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
