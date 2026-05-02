from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from issues import IssueDetail, issue_detail

CODEX_USER_AGENT = "codex-tui/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9 (codex-tui; 0.118.0)"
CODEX_ORIGINATOR = "codex-tui"

ImageQuality = Literal["auto"]
ImageResponseFormat = Literal["b64_json", "url"]
ImageJobStatus = Literal["queued", "running", "succeeded", "failed"]

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
    status: ImageJobStatus
    created_at: int
    updated_at: int
    previous_response_id: str | None = None
    upstream_response_id: str | None = None
    upstream_metadata: list[ImageUpstreamMetadata] = Field(default_factory=list)
    position: int | None = None
    references: list[ImageReferenceData] = Field(default_factory=list)
    result: ImageGenerationResponse | None = None
    error: IssueDetail | None = None


class ImageGenerationJobSummaryResponse(BaseModel):
    id: str
    conversation_id: str | None = None
    prompt: str
    size: str
    quality: str
    n: int
    status: ImageJobStatus
    created_at: int
    updated_at: int
    position: int | None = None
    error: IssueDetail | None = None


class ImageGenerationJobListResponse(BaseModel):
    items: list[ImageGenerationJobSummaryResponse]
    total_count: int


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
    status: ImageJobStatus
    created_at: int
    updated_at: int
    position: int | None = None
    references: list[ImageReferenceData] = Field(default_factory=list)
    upstream_metadata: list[ImageUpstreamMetadata] = Field(default_factory=list)
    error: IssueDetail | None = None


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
