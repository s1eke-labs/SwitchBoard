import type { ImageGalleryJob } from "@/lib/api";
import type { TranslationKey } from "@/i18n";

export const ASPECT_RATIO_OPTIONS = ["1:1", "3:4", "4:3", "9:16", "16:9", "21:9"] as const;
export const QUALITY_OPTIONS = ["low", "medium", "high"] as const;
export const IMAGE_COUNT_OPTIONS = [1, 2, 4] as const;
export const IMAGE_SIZE_BY_RATIO_AND_QUALITY = {
  "1:1": { low: "1024x1024", medium: "1536x1536", high: "2880x2880" },
  "3:4": { low: "768x1024", medium: "1536x2048", high: "2448x3264" },
  "4:3": { low: "1024x768", medium: "2048x1536", high: "3264x2448" },
  "9:16": { low: "720x1280", medium: "1152x2048", high: "2160x3840" },
  "16:9": { low: "1280x720", medium: "2048x1152", high: "3840x2160" },
  "21:9": { low: "1344x576", medium: "2688x1152", high: "3360x1440" },
} as const;

export const MAX_REFERENCE_IMAGES = 4;
export const MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024;
export const REFERENCE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
export const GALLERY_CARD_HEIGHT = 178;
export const GALLERY_GRID_GAP = 10;
export const GALLERY_MIN_COLUMN_WIDTH = 168;
export const GALLERY_DEFAULT_COLUMN_COUNT = 4;
export const GALLERY_DEFAULT_ROW_COUNT = 4;
export const GALLERY_MAX_PAGE_SIZE = GALLERY_DEFAULT_COLUMN_COUNT * GALLERY_DEFAULT_ROW_COUNT;
export const GALLERY_FALLBACK_PAGE_SIZE = GALLERY_MAX_PAGE_SIZE;

export const STATUS_LABEL_KEYS: Record<ImageGalleryJob["status"], TranslationKey> = {
  queued: "images.status.queued",
  running: "images.status.running",
  succeeded: "images.status.succeeded",
  failed: "images.status.failed",
};
