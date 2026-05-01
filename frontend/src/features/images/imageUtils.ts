import type {
  ImageGalleryItem,
  ImageGalleryJob,
  ImageGenerationJob,
  ImageGenerationResponse,
} from "@/lib/api";
import type { TranslationKey } from "@/i18n";
import {
  ASPECT_RATIO_OPTIONS,
  IMAGE_SIZE_BY_RATIO_AND_QUALITY,
  MAX_REFERENCE_IMAGE_BYTES,
  QUALITY_OPTIONS,
  REFERENCE_IMAGE_TYPES,
} from "@/features/images/constants";
import type { GalleryItem, ImageAspectRatio, ImageQuality, PendingReferenceImage } from "@/features/images/types";

export function imageSources(result: ImageGenerationResponse | null) {
  return (result?.data ?? [])
    .map((item) => {
      if (item.file_url) return item.file_url;
      if (item.url) return item.url;
      if (item.b64_json) return `data:image/png;base64,${item.b64_json}`;
      return null;
    })
    .filter((src): src is string => Boolean(src));
}

export function gallerySlotCount(job: ImageGenerationJob) {
  const sources = imageSources(job.result);
  return isActiveJob(job) ? Math.max(job.n, sources.length, 1) : Math.max(sources.length, 1);
}

export function galleryApiItemsFromJob(job: ImageGenerationJob): ImageGalleryItem[] {
  return Array.from({ length: gallerySlotCount(job) }, (_, index) => {
    const image = job.result?.data[index];
    return {
      key: `${job.id}:${index}`,
      job,
      image_index: index,
      image: image
        ? {
            url: image.file_url ?? image.url,
            revised_prompt: image.revised_prompt,
            file_name: image.file_name,
            file_url: image.file_url,
            thumbnail_url: image.thumbnail_url,
            width: image.width,
            height: image.height,
            size_bytes: image.size_bytes,
            duration_seconds: image.duration_seconds,
          }
        : null,
    };
  });
}

export function galleryItemsFromApiItems(items: ImageGalleryItem[]): GalleryItem[] {
  return items.map((item) => {
    return {
      key: item.key,
      job: item.job,
      thumbnailSrc: item.image?.thumbnail_url ?? null,
      fullSrc: item.image?.file_url ?? item.image?.url ?? null,
      index: item.image_index,
      revisedPrompt: item.image?.revised_prompt ?? null,
      width: item.image?.width ?? null,
      height: item.image?.height ?? null,
      sizeBytes: item.image?.size_bytes ?? null,
      durationSeconds: item.image?.duration_seconds ?? null,
    };
  });
}

export function isActiveJob(job: ImageGalleryJob) {
  return job.status === "queued" || job.status === "running";
}

export function isSelectableGalleryItem(item: GalleryItem) {
  return !isActiveJob(item.job) && (Boolean(item.fullSrc) || item.job.status === "failed");
}

export function downloadGalleryItem(item: GalleryItem) {
  if (!item.fullSrc) return;
  const anchor = document.createElement("a");
  anchor.href = item.fullSrc;
  anchor.download = `switchboard-image-${item.job.updated_at}-${item.index + 1}.png`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

export function imageSettingsFromSize(size: string): { aspectRatio: ImageAspectRatio; quality: ImageQuality } | null {
  for (const aspectRatio of ASPECT_RATIO_OPTIONS) {
    for (const quality of QUALITY_OPTIONS) {
      if (IMAGE_SIZE_BY_RATIO_AND_QUALITY[aspectRatio][quality] === size) {
        return { aspectRatio, quality };
      }
    }
  }
  return null;
}

export function imageStyleParts(size: string, quality: ImageGalleryJob["quality"], t: (key: TranslationKey) => string) {
  const settings = imageSettingsFromSize(size);
  if (settings) {
    return {
      aspectRatio: settings.aspectRatio,
      quality: t(`images.quality.${settings.quality}`),
    };
  }
  return {
    aspectRatio: size,
    quality: t(`images.quality.${quality}`),
  };
}

export function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

export function formatDuration(seconds: number) {
  const value = Math.max(0, Math.round(seconds));
  if (value < 60) return `${value}s`;
  const minutes = Math.floor(value / 60);
  const remainingSeconds = value % 60;
  if (minutes < 60) return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

export function formatJobTime(value: number) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}

function extensionFromMime(mimeType: string) {
  if (mimeType === "image/jpeg") return "jpg";
  if (mimeType === "image/webp") return "webp";
  return "png";
}

function mimeFromSource(src: string) {
  if (src.startsWith("data:image/jpeg")) return "image/jpeg";
  if (src.startsWith("data:image/webp")) return "image/webp";
  if (src.endsWith(".jpg") || src.endsWith(".jpeg")) return "image/jpeg";
  if (src.endsWith(".webp")) return "image/webp";
  return "image/png";
}

function blobToReference(blob: Blob, fileName: string): Promise<PendingReferenceImage> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = typeof reader.result === "string" ? reader.result : "";
      const [, b64Json = ""] = value.split(",", 2);
      if (!b64Json) {
        reject(new Error("invalid image data"));
        return;
      }
      resolve({
        id: crypto.randomUUID(),
        fileName,
        mimeType: blob.type || mimeFromSource(fileName),
        sizeBytes: blob.size,
        b64Json,
        previewUrl: URL.createObjectURL(blob),
      });
    };
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(blob);
  });
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = typeof reader.result === "string" ? reader.result : "";
      const [, b64Json = ""] = value.split(",", 2);
      if (!b64Json) {
        reject(new Error("invalid image data"));
        return;
      }
      resolve(b64Json);
    };
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(blob);
  });
}

export function fileToReference(file: File): Promise<PendingReferenceImage> {
  return blobToReference(file, file.name);
}

export async function sourceToReference(src: string, job: ImageGalleryJob, index: number) {
  const response = await fetch(src);
  if (!response.ok) throw new Error("fetch failed");
  const rawBlob = await response.blob();
  const mimeType = rawBlob.type && REFERENCE_IMAGE_TYPES.has(rawBlob.type) ? rawBlob.type : mimeFromSource(src);
  const blob = rawBlob.type === mimeType ? rawBlob : rawBlob.slice(0, rawBlob.size, mimeType);
  if (!REFERENCE_IMAGE_TYPES.has(mimeType)) throw new Error("unsupported type");
  if (blob.size > MAX_REFERENCE_IMAGE_BYTES) throw new Error("too large");
  const fileName = `switchboard-edit-${job.id}-${index + 1}.${extensionFromMime(mimeType)}`;
  return blobToReference(blob, fileName);
}
