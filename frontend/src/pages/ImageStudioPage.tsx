import { ChangeEvent, DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Modal } from "@heroui/react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  ImageIcon,
  Loader2,
  Palette,
  Plus,
  Pencil,
  X,
  XCircle,
  WandSparkles,
} from "lucide-react";
import { toast } from "sonner";
import { api, ImageGenerationJob, ImageGenerationRequest, ImageGenerationResponse } from "@/lib/api";
import type { ImageReferenceInput } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useI18n } from "@/i18n";
import type { TranslationKey } from "@/i18n";

const ASPECT_RATIO_OPTIONS = ["1:1", "3:4", "4:3", "9:16", "16:9", "21:9"] as const;
const QUALITY_OPTIONS = ["low", "medium", "high"] as const;
const IMAGE_COUNT_OPTIONS = [1, 2, 4] as const;
const IMAGE_SIZE_BY_RATIO_AND_QUALITY = {
  "1:1": { low: "1024x1024", medium: "1536x1536", high: "2880x2880" },
  "3:4": { low: "768x1024", medium: "1536x2048", high: "2448x3264" },
  "4:3": { low: "1024x768", medium: "2048x1536", high: "3264x2448" },
  "9:16": { low: "720x1280", medium: "1152x2048", high: "2160x3840" },
  "16:9": { low: "1280x720", medium: "2048x1152", high: "3840x2160" },
  "21:9": { low: "1344x576", medium: "2688x1152", high: "3360x1440" },
} as const;
const MAX_REFERENCE_IMAGES = 4;
const MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024;
const REFERENCE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const GALLERY_PAGE_SIZE = 24;

type ImageAspectRatio = (typeof ASPECT_RATIO_OPTIONS)[number];
type ImageQuality = (typeof QUALITY_OPTIONS)[number];
type ImageSize = (typeof IMAGE_SIZE_BY_RATIO_AND_QUALITY)[ImageAspectRatio][ImageQuality];
type ImageCount = (typeof IMAGE_COUNT_OPTIONS)[number];
type PendingReferenceImage = {
  id: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  b64Json: string;
  previewUrl: string;
};
type GalleryItem = {
  key: string;
  job: ImageGenerationJob;
  src: string | null;
  index: number;
};

const STATUS_LABEL_KEYS: Record<ImageGenerationJob["status"], TranslationKey> = {
  queued: "images.status.queued",
  running: "images.status.running",
  succeeded: "images.status.succeeded",
  failed: "images.status.failed",
};

function imageSources(result: ImageGenerationResponse | null) {
  return (result?.data ?? [])
    .map((item) => {
      if (item.file_url) return item.file_url;
      if (item.url) return item.url;
      if (item.b64_json) return `data:image/png;base64,${item.b64_json}`;
      return null;
    })
    .filter((src): src is string => Boolean(src));
}

function galleryItemsFromJobs(jobs: ImageGenerationJob[]): GalleryItem[] {
  return jobs.flatMap<GalleryItem>((job) => {
    const sources = imageSources(job.result);
    if (sources.length === 0) return [{ key: job.id, job, src: null, index: 0 }];
    return sources.map((src, index) => ({ key: `${job.id}:${index}`, job, src, index }));
  });
}

function isActiveJob(job: ImageGenerationJob) {
  return job.status === "queued" || job.status === "running";
}

function imageSettingsFromSize(size: string): { aspectRatio: ImageAspectRatio; quality: ImageQuality } | null {
  for (const aspectRatio of ASPECT_RATIO_OPTIONS) {
    for (const quality of QUALITY_OPTIONS) {
      if (IMAGE_SIZE_BY_RATIO_AND_QUALITY[aspectRatio][quality] === size) {
        return { aspectRatio, quality };
      }
    }
  }
  return null;
}

function formatImageStyleLabel(
  size: string,
  quality: ImageGenerationJob["quality"],
  t: (key: TranslationKey) => string,
) {
  const settings = imageSettingsFromSize(size);
  if (settings) {
    return `${settings.aspectRatio} · ${t(`images.quality.${settings.quality}`)}`;
  }
  return `${size} · ${t(`images.quality.${quality}`)}`;
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

function formatJobTime(value: number) {
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

function fileToReference(file: File): Promise<PendingReferenceImage> {
  return blobToReference(file, file.name);
}

async function sourceToReference(src: string, job: ImageGenerationJob, index: number) {
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

function JobStatusIcon({ job }: { job: ImageGenerationJob }) {
  if (job.status === "succeeded") return <CheckCircle2 size={15} className="text-emerald-600" />;
  if (job.status === "failed") return <XCircle size={15} className="text-destructive" />;
  if (job.status === "running") return <Loader2 size={15} className="animate-spin text-primary" />;
  return <Clock3 size={15} className="text-muted-foreground" />;
}

function SelectMenu<T extends string>({
  label,
  value,
  options,
  formatOption,
  open,
  placement = "down",
  onOpenChange,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly T[];
  formatOption: (value: T) => string;
  open: boolean;
  placement?: "up" | "down";
  onOpenChange: (open: boolean) => void;
  onChange: (value: T) => void;
}) {
  const menuPosition = placement === "up" ? "bottom-10" : "top-10";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-md border bg-white px-3 text-left text-sm font-semibold transition-colors hover:bg-muted"
      >
        <span className="truncate">
          <span className="text-muted-foreground">{label}</span>
          <span className="mx-1">·</span>
          {formatOption(value)}
        </span>
        <ChevronDown size={15} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className={`absolute left-0 right-0 ${menuPosition} z-20 overflow-hidden rounded-md border bg-white shadow-lg`}>
          {options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => {
                onChange(option);
                onOpenChange(false);
              }}
              className={`flex h-9 w-full items-center px-3 text-left text-sm transition-colors hover:bg-muted ${
                option === value ? "font-semibold text-primary" : "text-foreground"
              }`}
            >
              {formatOption(option)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function NumberSelectMenu<T extends number>({
  label,
  value,
  options,
  open,
  placement = "down",
  onOpenChange,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly T[];
  open: boolean;
  placement?: "up" | "down";
  onOpenChange: (open: boolean) => void;
  onChange: (value: T) => void;
}) {
  const menuPosition = placement === "up" ? "bottom-10" : "top-10";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-md border bg-white px-3 text-left text-sm font-semibold transition-colors hover:bg-muted"
      >
        <span className="truncate">
          <span className="text-muted-foreground">{label}</span>
          <span className="mx-1">·</span>
          {value}
        </span>
        <ChevronDown size={15} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className={`absolute left-0 right-0 ${menuPosition} z-20 overflow-hidden rounded-md border bg-white shadow-lg`}>
          {options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => {
                onChange(option);
                onOpenChange(false);
              }}
              className={`flex h-9 w-full items-center px-3 text-left text-sm transition-colors hover:bg-muted ${
                option === value ? "font-semibold text-primary" : "text-foreground"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PageSelector({
  page,
  totalPages,
  disabled,
  jumping,
  onSelect,
}: {
  page: number;
  totalPages: number;
  disabled: boolean;
  jumping: boolean;
  onSelect: (page: number) => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const pageCount = Math.max(1, totalPages);

  return (
    <div className={`relative ${jumping ? "opacity-70" : ""}`} aria-busy={jumping}>
      <button
        type="button"
        className="flex h-8 min-w-28 items-center justify-center gap-1 rounded-md px-2 text-center text-xs font-semibold text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
        onClick={() => setOpen((value) => !value)}
        disabled={disabled || pageCount <= 1}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span>{jumping ? t("common.loadingEllipsis") : t("common.pageLabel", { page: Math.min(page, pageCount), total: pageCount })}</span>
        <ChevronDown size={14} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className="absolute bottom-10 left-1/2 z-30 max-h-48 w-52 -translate-x-1/2 overflow-auto rounded-md border bg-white p-2 shadow-soft">
          <div className="grid grid-cols-4 gap-1" role="listbox" aria-label={t("common.selectPage")}>
            {Array.from({ length: pageCount }, (_, index) => {
              const pageNumber = index + 1;
              const active = pageNumber === page;
              return (
                <button
                  key={pageNumber}
                  type="button"
                  className={`h-8 rounded-md text-sm font-semibold transition-colors hover:bg-muted ${
                    active ? "bg-foreground text-white hover:bg-foreground" : "text-foreground"
                  }`}
                  onClick={() => {
                    setOpen(false);
                    onSelect(pageNumber);
                  }}
                  role="option"
                  aria-selected={active}
                >
                  {pageNumber}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ReferencePreviewModal({
  reference,
  onClose,
}: {
  reference: PendingReferenceImage;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Modal isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Backdrop variant="opaque">
        <Modal.Container placement="center" size="cover" className="p-3 sm:p-6">
          <Modal.Dialog className="max-h-[92vh] max-w-3xl overflow-hidden rounded-md bg-background p-0">
            <Modal.Header className="flex-row items-center justify-between gap-3 border-b px-4 py-3">
              <Modal.Heading className="truncate text-sm font-semibold">{t("images.references")}</Modal.Heading>
              <Button type="button" variant="ghost" size="icon" aria-label={t("images.closePreview")} onClick={onClose}>
                <X size={18} />
              </Button>
            </Modal.Header>
            <Modal.Body className="flex min-h-[320px] items-center justify-center bg-muted p-4">
              <img src={reference.previewUrl} alt={reference.fileName} className="max-h-[78vh] max-w-full rounded-md object-contain" />
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

function ImagePreviewModal({
  item,
  editing,
  onEdit,
  onClose,
}: {
  item: GalleryItem;
  editing: boolean;
  onEdit: (item: GalleryItem) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { job, src } = item;
  const revisedPrompt = job.result?.data.find((data) => data.revised_prompt)?.revised_prompt;
  const styleLabel = formatImageStyleLabel(job.size, job.quality, t);

  function handleDownload() {
    if (!src) return;
    const anchor = document.createElement("a");
    anchor.href = src;
    anchor.download = `switchboard-image-${job.result?.created ?? job.updated_at}-${item.index + 1}.png`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  return (
    <Modal isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Backdrop variant="opaque">
        <Modal.Container placement="center" size="cover" className="p-3 sm:p-6">
          <Modal.Dialog className="max-h-[92vh] max-w-5xl overflow-hidden rounded-md bg-background p-0">
            <Modal.Header className="flex-row items-center justify-between gap-3 border-b px-4 py-3">
              <Modal.Heading className="flex min-w-0 items-center gap-2">
                <JobStatusIcon job={job} />
                <span className="truncate text-sm font-semibold">{t(STATUS_LABEL_KEYS[job.status])}</span>
              </Modal.Heading>
              <div className="flex items-center gap-2">
                <Button variant="secondary" size="sm" disabled={!src} onClick={handleDownload}>
                  <Download size={15} />
                  {t("images.download")}
                </Button>
                <Button variant="secondary" size="sm" disabled={!src || editing} onClick={() => onEdit(item)}>
                  {editing ? <Loader2 size={15} className="animate-spin" /> : <Pencil size={15} />}
                  {t("images.edit")}
                </Button>
                <Button type="button" variant="ghost" size="icon" aria-label={t("images.closePreview")} onClick={onClose}>
                  <X size={18} />
                </Button>
              </div>
            </Modal.Header>
            <Modal.Body className="grid min-h-0 flex-1 gap-0 overflow-auto p-0 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="flex min-h-[360px] items-center justify-center bg-muted p-4">
                {src ? (
                  <img src={src} alt={revisedPrompt || t("images.preview")} className="max-h-[72vh] max-w-full rounded-md object-contain" />
                ) : (
                  <div className="flex items-center text-sm text-muted-foreground">
                    <JobStatusIcon job={job} />
                    <span className="ml-2">{t(STATUS_LABEL_KEYS[job.status])}</span>
                  </div>
                )}
              </div>
              <div className="space-y-4 overflow-auto border-t p-4 lg:border-l lg:border-t-0">
                <div>
                  <div className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground">
                    <Palette size={13} />
                    {t("images.style")}
                  </div>
                  <p className="text-sm leading-6">{styleLabel}</p>
                </div>
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{t("images.prompt")}</div>
                  <p className="whitespace-pre-wrap break-words text-sm leading-6">{job.prompt}</p>
                </div>
                {revisedPrompt ? (
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{t("images.revisedPrompt")}</div>
                    <p className="whitespace-pre-wrap break-words text-sm leading-6">{revisedPrompt}</p>
                  </div>
                ) : null}
                {job.references.length ? (
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{t("images.references")}</div>
                    <div className="grid grid-cols-2 gap-2">
                      {job.references.map((reference) => (
                        <div key={reference.id} className="overflow-hidden rounded-md border bg-white">
                          <img src={reference.file_url} alt={reference.original_file_name} className="aspect-square w-full object-cover" />
                          <div className="px-2 py-1.5 text-xs">
                            <div className="truncate font-semibold">{reference.original_file_name}</div>
                            <div className="text-muted-foreground">{formatBytes(reference.size_bytes)}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {job.error ? (
                  <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                    {job.error.message}
                  </div>
                ) : null}
              </div>
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

function ImageGallery({
  items,
  loading,
  onOpenPreview,
}: {
  items: GalleryItem[];
  loading: boolean;
  onOpenPreview: (key: string) => void;
}) {
  const { t } = useI18n();
  if (loading) {
    return (
      <div className="flex min-h-[456px] flex-1 items-center justify-center text-sm text-muted-foreground">
        <Loader2 size={18} className="mr-2 animate-spin" />
        {t("common.loading")}
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="flex min-h-[456px] flex-1 flex-col items-center justify-center text-sm text-muted-foreground">
        <ImageIcon size={32} className="mb-2" />
        {t("images.emptyGallery")}
      </div>
    );
  }
  return (
    <div className="grid auto-rows-[220px] grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {items.map((item) => {
        const statusLabel = t(STATUS_LABEL_KEYS[item.job.status]);
        const active = isActiveJob(item.job);
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onOpenPreview(item.key)}
            aria-label={`${t("images.preview")} · ${statusLabel}`}
            className="group flex h-[220px] min-w-0 flex-col overflow-hidden rounded-md border bg-white text-left transition-colors hover:border-primary/50 focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <div className="flex min-h-0 flex-1 items-center justify-center bg-muted/60 p-2">
              {item.src ? (
                <img src={item.src} alt={item.job.prompt} className="h-full w-full object-contain transition-transform group-hover:scale-[1.01]" />
              ) : (
                <div className="flex items-center text-muted-foreground" aria-label={statusLabel}>
                  <JobStatusIcon job={item.job} />
                </div>
              )}
            </div>
            <div className="h-11 shrink-0 border-t px-3 py-2.5">
              <div className="flex min-w-0 items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="flex min-w-0 items-center gap-1">
                  {active ? null : <JobStatusIcon job={item.job} />}
                  <span className="truncate">{statusLabel}</span>
                </span>
                <span className="shrink-0">{formatJobTime(item.job.updated_at)}</span>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function ImageStudioPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const referenceImagesRef = useRef<PendingReferenceImage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState<ImageAspectRatio>("1:1");
  const [quality, setQuality] = useState<ImageQuality>("low");
  const [imageCount, setImageCount] = useState<ImageCount>(1);
  const [aspectRatioOpen, setAspectRatioOpen] = useState(false);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [imageCountOpen, setImageCountOpen] = useState(false);
  const [referenceImages, setReferenceImages] = useState<PendingReferenceImage[]>([]);
  const [previewReferenceId, setPreviewReferenceId] = useState<string | null>(null);
  const [selectedItemKey, setSelectedItemKey] = useState<string | null>(null);
  const [galleryPage, setGalleryPage] = useState(1);
  const [editingItemKey, setEditingItemKey] = useState<string | null>(null);
  const trimmedPrompt = prompt.trim();

  const jobs = useQuery({
    queryKey: ["imageJobs", galleryPage],
    queryFn: () => api.imageJobs({ page: galleryPage, limit: GALLERY_PAGE_SIZE }),
    placeholderData: (previousData) => previousData,
    refetchInterval: (query) => {
      const data = query.state.data?.items;
      return data?.some(isActiveJob) ? 3000 : false;
    },
  });
  const jobItems = useMemo(() => jobs.data?.items ?? [], [jobs.data?.items]);
  const galleryItems = useMemo(() => galleryItemsFromJobs(jobItems), [jobItems]);
  const galleryTotalPages = Math.max(1, Math.ceil((jobs.data?.total_count ?? 0) / GALLERY_PAGE_SIZE));
  const selectedItem = useMemo(
    () => galleryItems.find((item) => item.key === selectedItemKey) ?? null,
    [galleryItems, selectedItemKey],
  );
  const previewReference = useMemo(
    () => referenceImages.find((reference) => reference.id === previewReferenceId) ?? null,
    [previewReferenceId, referenceImages],
  );

  useEffect(() => {
    referenceImagesRef.current = referenceImages;
  }, [referenceImages]);

  useEffect(() => {
    return () => {
      for (const reference of referenceImagesRef.current) {
        URL.revokeObjectURL(reference.previewUrl);
      }
    };
  }, []);

  useEffect(() => {
    if (!jobs.isFetching && galleryPage > galleryTotalPages) {
      setGalleryPage(galleryTotalPages);
    }
  }, [galleryPage, galleryTotalPages, jobs.isFetching]);

  const createJob = useMutation({
    mutationFn: (payload: ImageGenerationRequest) => api.createImageJob(payload),
    onSuccess: (job) => {
      setGalleryPage(1);
      queryClient.setQueryData(["imageJobs", 1], (current: typeof jobs.data | undefined) => {
        if (!current) return current;
        return {
          ...current,
                    items: [job, ...current.items.filter((item) => item.id !== job.id)].slice(0, GALLERY_PAGE_SIZE),
          total_count: current.total_count + (current.items.some((item) => item.id === job.id) ? 0 : 1),
        };
      });
      queryClient.invalidateQueries({ queryKey: ["imageJobs"] });
      for (const reference of referenceImages) {
        URL.revokeObjectURL(reference.previewUrl);
      }
      setReferenceImages([]);
      toast.success(t("images.jobQueued"));
    },
    onError: (error) => {
      toast.error(t("images.generateFailed"), {
        description: formatAppError(error),
      });
    },
  });

  async function addReferenceFiles(files: FileList | File[]) {
    const incoming = Array.from(files);
    const slots = MAX_REFERENCE_IMAGES - referenceImages.length;
    if (incoming.length > slots) {
      toast.error(t("images.referenceTooMany"));
    }
    const accepted = incoming.slice(0, Math.max(0, slots));
    const nextReferences: PendingReferenceImage[] = [];
    for (const file of accepted) {
      if (!REFERENCE_IMAGE_TYPES.has(file.type)) {
        toast.error(t("images.referenceUnsupported", { name: file.name }));
        continue;
      }
      if (file.size > MAX_REFERENCE_IMAGE_BYTES) {
        toast.error(t("images.referenceTooLarge", { name: file.name }));
        continue;
      }
      try {
        nextReferences.push(await fileToReference(file));
      } catch {
        toast.error(t("images.referenceReadFailed", { name: file.name }));
      }
    }
    if (nextReferences.length > 0) {
      setReferenceImages((current) => [...current, ...nextReferences]);
    }
  }

  function handleReferenceChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.currentTarget.files;
    if (files) void addReferenceFiles(files);
    event.currentTarget.value = "";
  }

  function handleReferenceDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void addReferenceFiles(event.dataTransfer.files);
  }

  function removeReference(id: string) {
    setReferenceImages((current) => {
      const removed = current.find((reference) => reference.id === id);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((reference) => reference.id !== id);
    });
  }

  async function handleEditItem(item: GalleryItem) {
    if (!item.src) return;
    setEditingItemKey(item.key);
    try {
      const reference = await sourceToReference(item.src, item.job, item.index);
      setReferenceImages((current) => {
        for (const existing of current) {
          URL.revokeObjectURL(existing.previewUrl);
        }
        return [reference];
      });
      setSelectedItemKey(null);
      window.setTimeout(() => textareaRef.current?.focus(), 0);
      toast.success(t("images.editReady"));
    } catch {
      toast.error(t("images.editReferenceFailed"));
    } finally {
      setEditingItemKey(null);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedPrompt || createJob.isPending) return;
    const references: ImageReferenceInput[] = referenceImages.map((reference) => ({
      file_name: reference.fileName,
      mime_type: reference.mimeType,
      b64_json: reference.b64Json,
    }));
    const selectedSize: ImageSize = IMAGE_SIZE_BY_RATIO_AND_QUALITY[aspectRatio][quality];
    createJob.mutate({
      prompt: trimmedPrompt,
      size: selectedSize,
      quality: "auto",
      n: imageCount,
      response_format: "b64_json",
      reference_images: references,
    });
    setPrompt("");
  }

  function selectGalleryPage(targetPage: number) {
    if (targetPage === galleryPage || targetPage < 1 || targetPage > galleryTotalPages || jobs.isFetching) return;
    setGalleryPage(targetPage);
    setSelectedItemKey(null);
  }

  return (
    <>
      <div className="grid min-h-[760px] w-full flex-1 grid-cols-1 gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="flex h-full min-h-0 flex-col overflow-hidden">
          <CardHeader>
            <div className="flex items-center gap-2">
              <WandSparkles size={18} className="text-primary" />
              <h2 className="text-base font-bold">{t("images.title")}</h2>
            </div>
          </CardHeader>
          <CardContent className="flex min-h-0 flex-1 flex-col p-0">
            <form className="flex min-h-0 flex-1 flex-col gap-3 p-4" onSubmit={handleSubmit}>
              <div
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleReferenceDrop}
                className="flex min-h-[360px] flex-1 flex-col rounded-md border bg-white p-3 focus-within:ring-2 focus-within:ring-ring"
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{t("images.prompt")}</span>
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    aria-label={t("images.addReference")}
                    className="flex h-8 w-8 items-center justify-center rounded-md border bg-white text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <Plus size={16} />
                  </button>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  multiple
                  className="hidden"
                  onChange={handleReferenceChange}
                />
                <div className="mb-3 grid h-16 grid-cols-4 gap-2">
                  {Array.from({ length: MAX_REFERENCE_IMAGES }, (_, index) => {
                    const reference = referenceImages[index];
                    return reference ? (
                      <div key={reference.id} className="relative overflow-hidden rounded-md border bg-muted">
                        <button type="button" onClick={() => setPreviewReferenceId(reference.id)} className="h-full w-full">
                          <img src={reference.previewUrl} alt={reference.fileName} className="h-full w-full object-cover" />
                        </button>
                        <button
                          type="button"
                          onClick={() => removeReference(reference.id)}
                          aria-label={t("images.referenceRemove")}
                          className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded bg-white/90 text-foreground shadow-soft hover:bg-white"
                        >
                          <X size={11} />
                        </button>
                      </div>
                    ) : (
                      <button
                        key={`reference-slot-${index}`}
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        aria-label={t("images.addReference")}
                        className="flex h-full items-center justify-center rounded-md border border-dashed bg-muted/40 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        {index === 0 && referenceImages.length === 0 ? <Plus size={15} /> : null}
                      </button>
                    );
                  })}
                </div>
                <textarea
                  ref={textareaRef}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder={t("images.promptPlaceholder")}
                  className="min-h-[190px] flex-1 resize-none border-0 bg-transparent p-0 text-sm leading-6 outline-none placeholder:text-muted-foreground"
                />
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <SelectMenu
                  label={t("images.size")}
                  value={aspectRatio}
                  options={ASPECT_RATIO_OPTIONS}
                  formatOption={(option) => option}
                  open={aspectRatioOpen}
                  placement="up"
                  onOpenChange={(open) => {
                    setAspectRatioOpen(open);
                    if (open) {
                      setQualityOpen(false);
                      setImageCountOpen(false);
                    }
                  }}
                  onChange={setAspectRatio}
                />
                <SelectMenu
                  label={t("images.quality")}
                  value={quality}
                  options={QUALITY_OPTIONS}
                  formatOption={(option) => t(`images.quality.${option}`)}
                  open={qualityOpen}
                  placement="up"
                  onOpenChange={(open) => {
                    setQualityOpen(open);
                    if (open) {
                      setAspectRatioOpen(false);
                      setImageCountOpen(false);
                    }
                  }}
                  onChange={setQuality}
                />
                <NumberSelectMenu
                  label={t("images.count")}
                  value={imageCount}
                  options={IMAGE_COUNT_OPTIONS}
                  open={imageCountOpen}
                  placement="up"
                  onOpenChange={(open) => {
                    setImageCountOpen(open);
                    if (open) {
                      setAspectRatioOpen(false);
                      setQualityOpen(false);
                    }
                  }}
                  onChange={setImageCount}
                />
              </div>

              <Button type="submit" className="w-full" disabled={!trimmedPrompt || createJob.isPending}>
                {createJob.isPending ? <Loader2 size={16} className="animate-spin" /> : <WandSparkles size={16} />}
                {createJob.isPending ? t("images.queueing") : t("images.generate")}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="flex min-h-[520px] flex-col overflow-hidden">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <ImageIcon size={18} className="text-primary" />
                <h2 className="truncate text-base font-bold">{t("images.gallery")}</h2>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  aria-label={t("common.previousPage")}
                  title={t("common.previousPage")}
                  variant="secondary"
                  size="icon"
                  className="h-8 w-8 rounded-md"
                  onClick={() => selectGalleryPage(Math.max(1, galleryPage - 1))}
                  disabled={galleryPage === 1 || jobs.isFetching}
                >
                  <ChevronLeft size={15} />
                </Button>
                <PageSelector
                  page={galleryPage}
                  totalPages={galleryTotalPages}
                  disabled={jobs.isFetching}
                  jumping={jobs.isFetching}
                  onSelect={selectGalleryPage}
                />
                <Button
                  aria-label={t("common.nextPage")}
                  title={t("common.nextPage")}
                  variant="secondary"
                  size="icon"
                  className="h-8 w-8 rounded-md"
                  onClick={() => selectGalleryPage(Math.min(galleryTotalPages, galleryPage + 1))}
                  disabled={galleryPage >= galleryTotalPages || jobs.isFetching}
                >
                  <ChevronRight size={15} />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="min-h-[456px] flex-1 overflow-auto p-4">
            <ImageGallery items={galleryItems} loading={jobs.isPending} onOpenPreview={setSelectedItemKey} />
          </CardContent>
        </Card>
      </div>

      {selectedItem ? (
        <ImagePreviewModal
          item={selectedItem}
          editing={editingItemKey === selectedItem.key}
          onEdit={handleEditItem}
          onClose={() => setSelectedItemKey(null)}
        />
      ) : null}
      {previewReference ? <ReferencePreviewModal reference={previewReference} onClose={() => setPreviewReferenceId(null)} /> : null}
    </>
  );
}
