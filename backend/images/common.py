from __future__ import annotations

import json

from pydantic import ValidationError

from .models import (
    ImageGenerationResponse,
    ImagePublicJobStatus,
    ImageUpstreamMetadata,
)


def public_job_status(status: str) -> ImagePublicJobStatus:
    if status == "queued":
        return "queued"
    if status in {"leased", "running"}:
        return "running"
    if status == "succeeded":
        return "succeeded"
    return "failed"


def upstream_metadata_json(result: ImageGenerationResponse) -> str | None:
    if not result.upstream_metadata:
        return None
    return json.dumps(
        [item.model_dump(mode="json", exclude_none=True) for item in result.upstream_metadata],
        ensure_ascii=False,
    )


def upstream_metadata_from_json(value: str | None) -> list[ImageUpstreamMetadata]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    metadata_items: list[ImageUpstreamMetadata] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            metadata_items.append(ImageUpstreamMetadata.model_validate(item))
        except ValidationError:
            continue
    return metadata_items


def priority_value(priority: str) -> int:
    return {"low": -10, "normal": 0, "high": 10}.get(priority, 0)


def local_or_dispatcher_source(source: str | None) -> str:
    return "external_dispatcher" if source == "external_dispatcher" else "local"

