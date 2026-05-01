import type { ImageGalleryJob } from "@/lib/api";
import {
  ASPECT_RATIO_OPTIONS,
  IMAGE_COUNT_OPTIONS,
  IMAGE_SIZE_BY_RATIO_AND_QUALITY,
  QUALITY_OPTIONS,
} from "@/features/images/constants";

export type ImageAspectRatio = (typeof ASPECT_RATIO_OPTIONS)[number];
export type ImageQuality = (typeof QUALITY_OPTIONS)[number];
export type ImageSize = (typeof IMAGE_SIZE_BY_RATIO_AND_QUALITY)[ImageAspectRatio][ImageQuality];
export type ImageCount = (typeof IMAGE_COUNT_OPTIONS)[number];
export type ImageOptionMenuKey = "aspectRatio" | "quality" | "imageCount";

export type PendingReferenceImage = {
  id: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  b64Json: string;
  previewUrl: string;
};

export type GalleryItem = {
  key: string;
  job: ImageGalleryJob;
  thumbnailSrc: string | null;
  fullSrc: string | null;
  index: number;
  revisedPrompt: string | null;
};
