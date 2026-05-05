from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from issues import IssueDetail, issue_detail

CODEX_USER_AGENT = "codex-tui/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9 (codex-tui; 0.118.0)"
CODEX_ORIGINATOR = "codex-tui"

ImageQuality = Literal["auto"]
ImageResponseFormat = Literal["b64_json", "url"]
ImageJobStatus = Literal["queued", "leased", "running", "succeeded", "failed", "canceled"]
ImagePublicJobStatus = Literal["queued", "running", "succeeded", "failed"]
ImageJobSource = Literal["local_ui", "local_api", "external_dispatcher", "retry"]
ImageJobPriority = Literal["low", "normal", "high"]
ImageWorkerRunStatus = Literal["executed", "no_job", "failed"]
ImageDispatcherConnectionStatus = Literal["unconfigured", "registering", "online", "offline", "auth_failed", "paused"]

IMAGE_MAX_SIDE_PX = 3840
IMAGE_SIZE_MULTIPLE_PX = 16
IMAGE_MAX_ASPECT_RATIO = 3
IMAGE_MIN_TOTAL_PIXELS = 655_360
IMAGE_MAX_TOTAL_PIXELS = 8_294_400
ALLOWED_IMAGE_QUALITIES = {"auto"}
ALLOWED_IMAGE_COUNTS = {1, 2, 4}
ALLOWED_IMAGE_RESPONSE_FORMATS = {"b64_json", "url"}
MAX_REFERENCE_IMAGES = 4
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_REFERENCE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_GENERATION_INSTRUCTIONS = "Use the image_generation tool to create an image from the user's prompt."
IMAGE_THUMBNAIL_MAX_SIDE_PX = 512
IMAGE_THUMBNAIL_SUFFIX = ".thumb.webp"
IMAGE_REFERENCES_DIR = "references"
IMAGE_OUTPUTS_DIR = "outputs"
IMAGE_DERIVED_DIR = "derived"
IMAGE_FILE_URL_PREFIX = "/api/images/files"


class ImageReferenceInput(BaseModel):
    file_name: str
    mime_type: str
    b64_json: str


class ImageReferenceData(BaseModel):
    id: str
    file_name: str
    file_url: str
    thumbnail_url: str | None = None
    original_file_name: str
    mime_type: str
    size_bytes: int


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: str | None = None
    size: str = "1024x1024"
    quality: str = "auto"
    n: int = 1
    response_format: str = "b64_json"
    reference_images: list[ImageReferenceInput] = Field(default_factory=list)
    conversation_id: str | None = None
    previous_response_id: str | None = None


class ImageData(BaseModel):
    b64_json: str | None = None
    url: str | None = None
    revised_prompt: str | None = None
    file_name: str | None = None
    file_url: str | None = None
    thumbnail_url: str | None = None
    saved_path: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    duration_seconds: int | None = None


class ImageUsageSummary(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None


class ImageToolUsageSummary(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    input_image_tokens: int | None = None
    input_text_tokens: int | None = None
    output_image_tokens: int | None = None
    output_text_tokens: int | None = None


class ImageUpstreamMetadata(BaseModel):
    response_id: str | None = None
    response_model: str | None = None
    image_model: str | None = None
    requested_size: str | None = None
    resolved_size: str | None = None
    quality: str | None = None
    output_format: str | None = None
    background: str | None = None
    moderation: str | None = None
    output_compression: int | None = None
    created_at: int | None = None
    completed_at: int | None = None
    duration_seconds: int | None = None
    usage: ImageUsageSummary | None = None
    image_usage: ImageToolUsageSummary | None = None


class ImageGenerationResponse(BaseModel):
    created: int
    model: str
    data: list[ImageData]
    response_id: str | None = None
    upstream_metadata: list[ImageUpstreamMetadata] = Field(default_factory=list)


class ImageGenerationJobResponse(BaseModel):
    id: str
    conversation_id: str | None = None
    prompt: str
    size: str
    quality: str
    n: int
    status: ImagePublicJobStatus
    created_at: int
    updated_at: int
    previous_response_id: str | None = None
    upstream_response_id: str | None = None
    upstream_metadata: list[ImageUpstreamMetadata] = Field(default_factory=list)
    position: int | None = None
    references: list[ImageReferenceData] = Field(default_factory=list)
    result: ImageGenerationResponse | None = None
    error: IssueDetail | None = None
    submission_id: str | None = None
    source: str = "local"
    source_label: str = "本地"
    dispatcher_id: str | None = None
    source_task_id: str | None = None


class ImageGenerationJobSummaryResponse(BaseModel):
    id: str
    conversation_id: str | None = None
    prompt: str
    size: str
    quality: str
    n: int
    status: ImagePublicJobStatus
    created_at: int
    updated_at: int
    position: int | None = None
    error: IssueDetail | None = None
    submission_id: str | None = None
    source: str = "local"
    source_label: str = "本地"
    dispatcher_id: str | None = None
    source_task_id: str | None = None


class ImageGenerationJobListResponse(BaseModel):
    items: list[ImageGenerationJobSummaryResponse]
    total_count: int


class ImageGenerationJobStatusResponse(BaseModel):
    id: str
    status: ImagePublicJobStatus
    updated_at: int
    position: int | None = None
    error: IssueDetail | None = None


class ImageGenerationJobStatusListResponse(BaseModel):
    items: list[ImageGenerationJobStatusResponse]
    total_count: int
    active_count: int


class ImageGalleryImageResponse(BaseModel):
    url: str | None = None
    revised_prompt: str | None = None
    file_name: str | None = None
    file_url: str | None = None
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    duration_seconds: int | None = None


class ImageGalleryJobResponse(BaseModel):
    id: str
    prompt: str
    size: str
    quality: str
    n: int
    status: ImagePublicJobStatus
    created_at: int
    updated_at: int
    position: int | None = None
    references: list[ImageReferenceData] = Field(default_factory=list)
    upstream_metadata: list[ImageUpstreamMetadata] = Field(default_factory=list)
    error: IssueDetail | None = None
    submission_id: str | None = None
    source: str = "local"
    source_label: str = "本地"
    dispatcher_id: str | None = None
    source_task_id: str | None = None


class ImageGalleryItemResponse(BaseModel):
    key: str
    job: ImageGalleryJobResponse
    image_index: int
    image: ImageGalleryImageResponse | None = None


class ImageGalleryListResponse(BaseModel):
    items: list[ImageGalleryItemResponse]
    total_count: int


class ImageGenerationError(Exception):
    def __init__(self, status_code: int, detail: IssueDetail) -> None:
        super().__init__(detail.message)
        self.status_code = status_code
        self.detail = detail



def _image_error(status_code: int, code: str, message: str) -> ImageGenerationError:
    return ImageGenerationError(status_code, issue_detail(code, message))


class ImageJobSubmitPayload(BaseModel):
    prompt: str
    model: str | None = None
    size: str = "1024x1024"
    quality: str = "auto"
    n: int = 1
    response_format: str = "b64_json"
    reference_images: list[ImageReferenceInput] = Field(default_factory=list)
    conversation_id: str | None = None
    previous_response_id: str | None = None

    def to_generation_request(self) -> ImageGenerationRequest:
        return ImageGenerationRequest.model_validate(self.model_dump())


class ImageJobSubmitRequest(BaseModel):
    source: ImageJobSource = "local_ui"
    source_task_id: str | None = None
    idempotency_key: str
    queue: str = "default"
    priority: ImageJobPriority = "normal"
    payload: ImageJobSubmitPayload
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageJobSubmitResponse(BaseModel):
    submission_id: str
    job_ids: list[str]
    created: bool


class ImageJobLease(BaseModel):
    job_id: str
    lease_owner: str
    lease_token: str
    lease_expires_at: int
    attempt_count: int


class ImageWorkerRunResult(BaseModel):
    status: ImageWorkerRunStatus
    job_id: str | None = None
    error: IssueDetail | None = None


class ImageWorkerDrainResult(BaseModel):
    executed: int
    failed: int
    stopped_reason: Literal["no_job", "max_jobs", "timeout"]


class ImageDispatcherTokenSummary(BaseModel):
    configured: bool
    preview: str | None = None


class ImageTaskDispatcherSettingsRequest(BaseModel):
    name: str
    api_base_url: str
    token: str | None = None


class ImageTaskDispatcherSettingsResponse(BaseModel):
    configured: bool
    name: str | None = None
    api_base_url: str | None = None
    token: ImageDispatcherTokenSummary = Field(default_factory=lambda: ImageDispatcherTokenSummary(configured=False))
    paused: bool = False
    external_runner_id: str | None = None
    external_runner_status: ImageDispatcherConnectionStatus = "unconfigured"
    external_heartbeat_interval_seconds: int | None = None
    external_poll_interval_seconds: int | None = None
    external_last_heartbeat_at: int | None = None
    external_last_claim_at: int | None = None
    external_current_task_id: str | None = None
    external_last_error: str | None = None


class ImageDispatcherTestRequest(BaseModel):
    name: str | None = None
    api_base_url: str | None = None
    token: str | None = None


class ImageDispatcherActionResponse(BaseModel):
    ok: bool
    settings: ImageTaskDispatcherSettingsResponse


class ImageExternalResultImage(BaseModel):
    index: int
    file_url: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    duration_seconds: int | None = None


class ImageExternalResultPayload(BaseModel):
    source_task_id: str | None = None
    submission_id: str
    status: Literal["succeeded", "failed", "canceled"]
    created_at: int
    finished_at: int
    images: list[ImageExternalResultImage] = Field(default_factory=list)
    upstream: dict[str, Any] = Field(default_factory=dict)
    error: IssueDetail | None = None


class ImageRunningExternalTaskResponse(BaseModel):
    id: str
    source_task_id: str | None = None
    prompt: str
    status: ImageJobStatus
    started_at: int | None = None
    updated_at: int
    lease_owner: str | None = None


class ImageWorkerStatusResponse(BaseModel):
    active_worker_running: bool
    active_worker_slots: int
    dispatcher: ImageTaskDispatcherSettingsResponse
    active_leases: int
    queued_jobs: int
    running_jobs: int
    running_external_tasks: list[ImageRunningExternalTaskResponse] = Field(default_factory=list)
