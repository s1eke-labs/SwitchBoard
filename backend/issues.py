from __future__ import annotations

import re

from fastapi import HTTPException
from pydantic import BaseModel


class IssueDetail(BaseModel):
    code: str
    message: str


def issue_detail(code: str, message: str) -> IssueDetail:
    return IssueDetail(code=code, message=message)


def http_error_from_detail(status_code: int, detail: IssueDetail) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail.model_dump())


def http_error(status_code: int, code: str, message: str) -> HTTPException:
    return http_error_from_detail(status_code, issue_detail(code, message))


def account_not_found_detail() -> IssueDetail:
    return issue_detail("ACCOUNT_NOT_FOUND", "Account not found")


def account_auth_not_found_detail() -> IssueDetail:
    return issue_detail("ACCOUNT_AUTH_NOT_FOUND", "Account auth not found")


def session_not_found_detail() -> IssueDetail:
    return issue_detail("SESSIONS_NOT_FOUND", "Session not found")


def session_event_not_found_detail() -> IssueDetail:
    return issue_detail("SESSIONS_EVENT_NOT_FOUND", "Session event not found")


def account_issue_from_message(message: str) -> IssueDetail:
    known = {
        "Cannot hide the current Codex account": issue_detail(
            "ACCOUNT_HIDE_CURRENT_FORBIDDEN", "Cannot hide the current Codex account"
        ),
        "auth.json does not contain ChatGPT tokens": issue_detail(
            "ACCOUNT_AUTH_TOKENS_MISSING", "auth.json does not contain ChatGPT tokens"
        ),
        "auth.json does not contain tokens.account_id": issue_detail(
            "ACCOUNT_AUTH_ACCOUNT_ID_MISSING", "auth.json does not contain tokens.account_id"
        ),
        "auth.json does not contain tokens.access_token": issue_detail(
            "ACCOUNT_AUTH_ACCESS_TOKEN_MISSING", "auth.json does not contain tokens.access_token"
        ),
        "Invalid account_id": issue_detail("ACCOUNT_INVALID_ID", "Invalid account_id"),
        "Stored auth account_id does not match requested account": issue_detail(
            "ACCOUNT_STORED_AUTH_MISMATCH", "Stored auth account_id does not match requested account"
        ),
    }
    if message in known:
        return known[message]
    if message.endswith(" does not exist"):
        return account_auth_not_found_detail()
    return issue_detail("ACCOUNT_INVALID_REQUEST", message)


def scan_warning_from_message(message: str) -> IssueDetail:
    detail = account_issue_from_message(message)
    if detail.code == "ACCOUNT_INVALID_REQUEST":
        return issue_detail("ACCOUNT_SCAN_WARNING", message)
    return detail


def config_import_issue_from_message(message: str) -> IssueDetail:
    if message == "Config import must be a JSON object":
        return issue_detail("CONFIG_IMPORT_INVALID_PAYLOAD", message)
    if message.startswith("Unsupported config schema; expected "):
        return issue_detail("CONFIG_IMPORT_INVALID_SCHEMA", message)
    if message == "accounts must be a list":
        return issue_detail("CONFIG_IMPORT_ACCOUNTS_NOT_LIST", message)
    if message == "account item must be an object":
        return issue_detail("CONFIG_IMPORT_ACCOUNT_ITEM_INVALID", message)
    if message == "account_id must be a non-empty string":
        return issue_detail("CONFIG_IMPORT_ACCOUNT_ID_REQUIRED", message)
    if message == "account_id is invalid":
        return issue_detail("CONFIG_IMPORT_ACCOUNT_ID_INVALID", message)
    if message == "hidden must be a boolean":
        return issue_detail("CONFIG_IMPORT_HIDDEN_INVALID", message)
    if re.match(r"^.+\.remaining_percent must be (a number|between 0 and 100)$", message):
        return issue_detail("CONFIG_IMPORT_LIMIT_INVALID", message)
    if re.match(r"^.+ must be (a string or null|a boolean|an integer or null|an object or null)$", message):
        return issue_detail("CONFIG_IMPORT_FIELD_TYPE_INVALID", message)
    return issue_detail("CONFIG_IMPORT_INVALID", message)


def sessions_issue_from_message(message: str) -> IssueDetail:
    known = {
        "Invalid cursor": issue_detail("SESSIONS_INVALID_CURSOR", "Invalid cursor"),
        "Invalid event cursor": issue_detail("SESSIONS_INVALID_EVENT_CURSOR", "Invalid event cursor"),
        "Invalid page": issue_detail("SESSIONS_INVALID_PAGE", "Invalid page"),
        "Session event is missing line metadata": issue_detail(
            "SESSIONS_EVENT_LINE_METADATA_MISSING", "Session event is missing line metadata"
        ),
    }
    return known.get(message, issue_detail("SESSIONS_INVALID_REQUEST", message))


def usage_issue_from_message(message: str) -> IssueDetail:
    known = {
        "Invalid cursor": issue_detail("USAGE_INVALID_CURSOR", "Invalid cursor"),
        "Invalid page": issue_detail("USAGE_INVALID_PAGE", "Invalid page"),
    }
    return known.get(message, issue_detail("USAGE_INVALID_REQUEST", message))
