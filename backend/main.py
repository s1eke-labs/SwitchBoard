from __future__ import annotations

import asyncio
import hmac
import logging
import time
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from accounts import AccountDTO, ScanResult, hide_account, list_accounts, scan_current_account, set_account_custom_name, switch_account
from config import get_settings, validate_runtime_settings
from config_transfer import ConfigExportDTO, ConfigImportSummary, export_config, import_config
from db import init_db
from images import (
    ImageGalleryListResponse,
    ImageGenerationError,
    ImageGenerationJobListResponse,
    ImageGenerationJobResponse,
    ImageGenerationJobStatusListResponse,
    ImageGenerationQueue,
    ImageGenerationRequest,
    ImageGenerationResponse,
    generate_image,
    image_file_path,
)
from issues import (
    account_auth_not_found_detail,
    account_issue_from_message,
    account_not_found_detail,
    config_import_issue_from_message,
    http_error,
    http_error_from_detail,
    session_event_not_found_detail,
    session_not_found_detail,
    sessions_issue_from_message,
    usage_issue_from_message,
)
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
from vault_crypto import ensure_auth_vault_key
from version import __version__


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
    ensure_auth_vault_key(settings)
    account_scan_lock = asyncio.Lock()
    image_queue = ImageGenerationQueue(settings)

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
        await image_queue.start()
        app.state.usage_aggregation_task = usage_task
        app.state.account_refresh_task = account_task
        try:
            yield
        finally:
            await image_queue.close()
            usage_task.cancel()
            account_task.cancel()
            with suppress(asyncio.CancelledError):
                await usage_task
            with suppress(asyncio.CancelledError):
                await account_task

    app = FastAPI(title="SwitchBoard", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.image_queue = image_queue

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest, response: Response) -> LoginResponse:
        if not hmac.compare_digest(payload.password, settings.app_password):
            raise http_error(status.HTTP_401_UNAUTHORIZED, "AUTH_INVALID_PASSWORD", "Invalid password")
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
            raise http_error_from_detail(status.HTTP_400_BAD_REQUEST, account_issue_from_message(str(exc))) from exc

    @app.post("/api/accounts/{account_id}/switch", response_model=ScanResult, dependencies=authed)
    async def switch_current_account(account_id: str) -> ScanResult:
        try:
            async with account_scan_lock:
                return await switch_account(settings, account_id)
        except KeyError as exc:
            raise http_error_from_detail(status.HTTP_404_NOT_FOUND, account_auth_not_found_detail()) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise http_error_from_detail(status.HTTP_400_BAD_REQUEST, account_issue_from_message(str(exc))) from exc

    @app.post("/api/accounts/{account_id}/hide", response_model=dict[str, bool], dependencies=authed)
    def hide(account_id: str) -> dict[str, bool]:
        try:
            hide_account(settings, account_id)
        except ValueError as exc:
            raise http_error_from_detail(status.HTTP_400_BAD_REQUEST, account_issue_from_message(str(exc))) from exc
        except KeyError as exc:
            raise http_error_from_detail(status.HTTP_404_NOT_FOUND, account_not_found_detail()) from exc
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/name", response_model=AccountDTO, dependencies=authed)
    def rename_account(account_id: str, payload: AccountNameRequest) -> AccountDTO:
        try:
            return set_account_custom_name(settings, account_id, payload.custom_name)
        except KeyError as exc:
            raise http_error_from_detail(status.HTTP_404_NOT_FOUND, account_not_found_detail()) from exc

    @app.get("/api/config/export", response_model=ConfigExportDTO, dependencies=authed)
    def export_switchboard_config() -> ConfigExportDTO:
        return export_config(settings)

    @app.post("/api/config/import", response_model=ConfigImportSummary, dependencies=authed)
    async def import_switchboard_config(request: Request) -> ConfigImportSummary:
        try:
            payload = await request.json()
            return import_config(settings, payload)
        except ValueError as exc:
            raise http_error_from_detail(status.HTTP_400_BAD_REQUEST, config_import_issue_from_message(str(exc))) from exc

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
            raise http_error_from_detail(status.HTTP_400_BAD_REQUEST, sessions_issue_from_message(str(exc))) from exc

    @app.get("/api/sessions/{thread_id}", response_model=SessionDetail, dependencies=authed)
    def session_detail(thread_id: str) -> SessionDetail:
        try:
            return get_session_detail(settings, thread_id)
        except KeyError as exc:
            raise http_error_from_detail(status.HTTP_404_NOT_FOUND, session_not_found_detail()) from exc

    @app.get("/api/sessions/{thread_id}/events", response_model=SessionEventsResponse, dependencies=authed)
    def session_events(thread_id: str, cursor: str | None = None, limit: int = 100) -> SessionEventsResponse:
        try:
            return list_session_events(settings, thread_id, cursor=cursor, limit=limit)
        except ValueError as exc:
            raise http_error_from_detail(status.HTTP_400_BAD_REQUEST, sessions_issue_from_message(str(exc))) from exc
        except KeyError as exc:
            raise http_error_from_detail(status.HTTP_404_NOT_FOUND, session_not_found_detail()) from exc

    @app.get("/api/sessions/{thread_id}/user-index", response_model=SessionUserIndexResponse, dependencies=authed)
    def session_user_index(thread_id: str) -> SessionUserIndexResponse:
        try:
            return list_session_user_index(settings, thread_id)
        except KeyError as exc:
            raise http_error_from_detail(status.HTTP_404_NOT_FOUND, session_not_found_detail()) from exc

    @app.get("/api/sessions/{thread_id}/events/{line_no}", response_model=SessionEvent, dependencies=authed)
    def session_event(thread_id: str, line_no: int) -> SessionEvent:
        try:
            return get_session_event(settings, thread_id, line_no)
        except KeyError as exc:
            raise http_error_from_detail(status.HTTP_404_NOT_FOUND, session_event_not_found_detail()) from exc

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
        account_id: str | None = None,
    ) -> UsageRequestLogsResponse:
        try:
            return get_usage_request_logs(
                settings,
                from_value=from_,
                to_value=to,
                limit=limit,
                cursor=cursor,
                page=page,
                account_id=account_id,
            )
        except ValueError as exc:
            raise http_error_from_detail(status.HTTP_400_BAD_REQUEST, usage_issue_from_message(str(exc))) from exc

    @app.post("/api/images/generations", response_model=ImageGenerationResponse, dependencies=authed)
    async def image_generations(payload: ImageGenerationRequest) -> ImageGenerationResponse:
        try:
            return await generate_image(settings, payload)
        except ImageGenerationError as exc:
            logger.warning("Image generation failed: %s", exc.detail.message)
            raise http_error_from_detail(exc.status_code, exc.detail) from exc

    @app.post("/api/images/jobs", response_model=ImageGenerationJobResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=authed)
    async def create_image_job(payload: ImageGenerationRequest) -> ImageGenerationJobResponse:
        try:
            return await image_queue.enqueue(payload)
        except ImageGenerationError as exc:
            raise http_error_from_detail(exc.status_code, exc.detail) from exc

    @app.get("/api/images/jobs", response_model=ImageGenerationJobListResponse, dependencies=authed)
    async def image_jobs(page: int = 1, limit: int = 20) -> ImageGenerationJobListResponse:
        try:
            return await image_queue.list_recent(page=page, limit=max(1, min(limit, 50)))
        except ImageGenerationError as exc:
            raise http_error_from_detail(exc.status_code, exc.detail) from exc

    @app.get("/api/images/jobs/statuses", response_model=ImageGenerationJobStatusListResponse, dependencies=authed)
    async def image_job_statuses(ids: Annotated[list[str] | None, Query()] = None) -> ImageGenerationJobStatusListResponse:
        tracked_ids = [job_id for job_id in dict.fromkeys(ids or []) if job_id][:100]
        return await image_queue.list_statuses(tracked_job_ids=tracked_ids)

    @app.get("/api/images/gallery", response_model=ImageGalleryListResponse, dependencies=authed)
    async def image_gallery(page: int = 1, limit: int = 20) -> ImageGalleryListResponse:
        try:
            return await image_queue.list_gallery_items(page=page, limit=max(1, min(limit, 50)))
        except ImageGenerationError as exc:
            raise http_error_from_detail(exc.status_code, exc.detail) from exc

    @app.get("/api/images/jobs/{job_id}", response_model=ImageGenerationJobResponse, dependencies=authed)
    async def image_job(job_id: str) -> ImageGenerationJobResponse:
        job = await image_queue.get(job_id)
        if job is None:
            raise http_error(status.HTTP_404_NOT_FOUND, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
        return job

    @app.delete("/api/images/jobs/{job_id}/images/{image_index}", response_model=dict[str, bool], dependencies=authed)
    async def delete_image_job_result(job_id: str, image_index: int) -> dict[str, bool]:
        try:
            await image_queue.delete_result_image(job_id, image_index)
        except ImageGenerationError as exc:
            raise http_error_from_detail(exc.status_code, exc.detail) from exc
        return {"ok": True}

    @app.delete("/api/images/jobs/{job_id}", response_model=dict[str, bool], dependencies=authed)
    async def delete_image_job(job_id: str) -> dict[str, bool]:
        try:
            await image_queue.delete_job(job_id)
        except ImageGenerationError as exc:
            raise http_error_from_detail(exc.status_code, exc.detail) from exc
        return {"ok": True}

    @app.get("/api/images/files/{file_path:path}", dependencies=authed)
    def image_file(file_path: str) -> FileResponse:
        try:
            path = image_file_path(settings, file_path)
        except ValueError as exc:
            raise http_error(status.HTTP_400_BAD_REQUEST, "IMAGE_FILE_INVALID", "Invalid image filename") from exc
        if not path.exists() or not path.is_file():
            raise http_error(status.HTTP_404_NOT_FOUND, "IMAGE_FILE_NOT_FOUND", "Image file not found")
        return FileResponse(path)

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
