import { ChangeEvent, DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock3, Download, ImageIcon, Loader2, Upload, X, XCircle, WandSparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ImageGenerationJob, ImageGenerationRequest, ImageGenerationResponse } from "@/lib/api";
import type { ImageReferenceInput } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useI18n } from "@/i18n";
import type { TranslationKey } from "@/i18n";

const SIZE_OPTIONS = ["1024x1024", "1024x1536", "1536x1024", "auto"] as const;
const QUALITY_OPTIONS = ["auto", "low", "medium", "high"] as const;
const MAX_REFERENCE_IMAGES = 4;
const MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024;
const REFERENCE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

type ImageSize = (typeof SIZE_OPTIONS)[number];
type ImageQuality = (typeof QUALITY_OPTIONS)[number];
type PendingReferenceImage = {
  id: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  b64Json: string;
  previewUrl: string;
};
const STATUS_LABEL_KEYS: Record<ImageGenerationJob["status"], TranslationKey> = {
  queued: "images.status.queued",
  running: "images.status.running",
  succeeded: "images.status.succeeded",
  failed: "images.status.failed",
};

function imageSource(result: ImageGenerationResponse | null) {
  const item = result?.data[0];
  if (!item) return null;
  if (item.file_url) return item.file_url;
  if (item.url) return item.url;
  if (item.b64_json) return `data:image/png;base64,${item.b64_json}`;
  return null;
}

function isActiveJob(job: ImageGenerationJob) {
  return job.status === "queued" || job.status === "running";
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

function fileToReference(file: File): Promise<PendingReferenceImage> {
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
        fileName: file.name,
        mimeType: file.type,
        sizeBytes: file.size,
        b64Json,
        previewUrl: URL.createObjectURL(file),
      });
    };
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

function OptionButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`h-8 rounded-md px-2.5 text-sm font-semibold transition-colors ${
        active ? "bg-foreground text-white" : "bg-white text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );
}

function JobStatusIcon({ job }: { job: ImageGenerationJob }) {
  if (job.status === "succeeded") return <CheckCircle2 size={15} className="text-emerald-600" />;
  if (job.status === "failed") return <XCircle size={15} className="text-destructive" />;
  if (job.status === "running") return <Loader2 size={15} className="animate-spin text-primary" />;
  return <Clock3 size={15} className="text-muted-foreground" />;
}

export function ImageStudioPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const referenceImagesRef = useRef<PendingReferenceImage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState<ImageSize>("1024x1024");
  const [quality, setQuality] = useState<ImageQuality>("high");
  const [referenceImages, setReferenceImages] = useState<PendingReferenceImage[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const trimmedPrompt = prompt.trim();
  const jobs = useQuery({
    queryKey: ["imageJobs"],
    queryFn: () => api.imageJobs(),
    refetchInterval: (query) => {
      const data = query.state.data as ImageGenerationJob[] | undefined;
      return data?.some(isActiveJob) ? 3000 : false;
    },
  });
  const selectedJob = useMemo(() => {
    if (selectedJobId) {
      return jobs.data?.find((job) => job.id === selectedJobId) ?? null;
    }
    return jobs.data?.find((job) => job.status === "succeeded") ?? jobs.data?.[0] ?? null;
  }, [jobs.data, selectedJobId]);
  const result = selectedJob?.result ?? null;
  const previewSrc = useMemo(() => imageSource(result), [result]);
  const revisedPrompt = result?.data[0]?.revised_prompt;

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

  const createJob = useMutation({
    mutationFn: (payload: ImageGenerationRequest) => api.createImageJob(payload),
    onSuccess: (job) => {
      setSelectedJobId(job.id);
      queryClient.setQueryData<ImageGenerationJob[]>(["imageJobs"], (current) => [
        job,
        ...(current ?? []).filter((item) => item.id !== job.id),
      ]);
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

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedPrompt || createJob.isPending) return;
    const references: ImageReferenceInput[] = referenceImages.map((reference) => ({
      file_name: reference.fileName,
      mime_type: reference.mimeType,
      b64_json: reference.b64Json,
    }));
    createJob.mutate({
      prompt: trimmedPrompt,
      size,
      quality,
      response_format: "b64_json",
      reference_images: references,
    });
  }

  function handleDownload() {
    if (!previewSrc) return;
    const anchor = document.createElement("a");
    anchor.href = previewSrc;
    anchor.download = `switchboard-image-${result?.created ?? Date.now()}.png`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
      <Card className="h-fit">
        <CardHeader>
          <div className="flex items-center gap-2">
            <WandSparkles size={18} className="text-primary" />
            <h2 className="text-base font-bold">{t("images.title")}</h2>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={handleSubmit}>
            <label className="block space-y-2">
              <span className="text-sm font-semibold">{t("images.prompt")}</span>
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={t("images.promptPlaceholder")}
                className="min-h-40 w-full resize-y rounded-md border bg-white px-3 py-2 text-sm leading-6 outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>

            <div className="space-y-2">
              <span className="text-sm font-semibold">{t("images.size")}</span>
              <div className="flex flex-wrap gap-1 rounded-lg border bg-muted p-1">
                {SIZE_OPTIONS.map((option) => (
                  <OptionButton
                    key={option}
                    active={size === option}
                    label={option}
                    onClick={() => setSize(option)}
                  />
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <span className="text-sm font-semibold">{t("images.quality")}</span>
              <div className="flex flex-wrap gap-1 rounded-lg border bg-muted p-1">
                {QUALITY_OPTIONS.map((option) => (
                  <OptionButton
                    key={option}
                    active={quality === option}
                    label={t(`images.quality.${option}`)}
                    onClick={() => setQuality(option)}
                  />
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <span className="text-sm font-semibold">{t("images.references")}</span>
              <div
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleReferenceDrop}
                className="rounded-md border border-dashed bg-white p-3"
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  multiple
                  className="hidden"
                  onChange={handleReferenceChange}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="flex min-h-20 w-full flex-col items-center justify-center rounded-md bg-muted px-3 py-4 text-center text-sm text-muted-foreground transition-colors hover:bg-muted/80"
                >
                  <Upload size={20} className="mb-2" />
                  <span className="font-semibold text-foreground">{t("images.referencesDrop")}</span>
                  <span className="mt-1 text-xs">{t("images.referencesHint")}</span>
                </button>
                {referenceImages.length > 0 ? (
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {referenceImages.map((reference) => (
                      <div key={reference.id} className="overflow-hidden rounded-md border bg-white">
                        <div className="relative aspect-square bg-muted">
                          <img
                            src={reference.previewUrl}
                            alt={reference.fileName}
                            className="h-full w-full object-cover"
                          />
                          <button
                            type="button"
                            onClick={() => removeReference(reference.id)}
                            aria-label={t("images.referenceRemove")}
                            className="absolute right-1 top-1 flex h-7 w-7 items-center justify-center rounded-md bg-white/90 text-foreground shadow-soft hover:bg-white"
                          >
                            <X size={14} />
                          </button>
                        </div>
                        <div className="space-y-0.5 px-2 py-1.5 text-xs">
                          <div className="truncate font-semibold">{reference.fileName}</div>
                          <div className="text-muted-foreground">{formatBytes(reference.sizeBytes)}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>

            <Button type="submit" className="w-full" disabled={!trimmedPrompt || createJob.isPending}>
              {createJob.isPending ? <Loader2 size={16} className="animate-spin" /> : <WandSparkles size={16} />}
              {createJob.isPending ? t("images.queueing") : t("images.generate")}
            </Button>
          </form>

          <div className="mt-5 space-y-2">
            <div className="text-sm font-semibold">{t("images.queue")}</div>
            <div className="space-y-2">
              {(jobs.data ?? []).slice(0, 5).map((job) => (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => setSelectedJobId(job.id)}
                  className={`flex min-h-10 w-full items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                    selectedJob?.id === job.id ? "border-primary bg-primary/5" : "bg-white hover:bg-muted"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <JobStatusIcon job={job} />
                    <span className="min-w-0">
                      <span className="block truncate">{job.prompt}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {t(STATUS_LABEL_KEYS[job.status])}
                        {job.references.length > 0 ? ` · ${t("images.referencesCount", { count: job.references.length })}` : ""}
                      </span>
                    </span>
                  </span>
                  {job.position ? (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {t("images.queuePosition", { position: job.position })}
                    </span>
                  ) : null}
                </button>
              ))}
              {jobs.isPending ? (
                <div className="flex h-10 items-center text-sm text-muted-foreground">
                  <Loader2 size={15} className="mr-2 animate-spin" />
                  {t("common.loading")}
                </div>
              ) : (jobs.data ?? []).length === 0 ? (
                <div className="rounded-md border bg-white px-3 py-2 text-sm text-muted-foreground">
                  {t("images.queueEmpty")}
                </div>
              ) : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="min-h-[520px] overflow-hidden">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <ImageIcon size={18} className="text-primary" />
              <h2 className="text-base font-bold">{t("images.preview")}</h2>
            </div>
            <Button variant="secondary" size="sm" disabled={!previewSrc} onClick={handleDownload}>
              <Download size={15} />
              {t("images.download")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex min-h-[456px] flex-col">
          <div className="flex min-h-[360px] flex-1 items-center justify-center rounded-md border bg-muted p-3">
            {selectedJob && isActiveJob(selectedJob) ? (
              <div className="flex items-center text-sm text-muted-foreground">
                <Loader2 size={18} className="mr-2 animate-spin" />
                {t(STATUS_LABEL_KEYS[selectedJob.status])}
              </div>
            ) : previewSrc ? (
              <img
                src={previewSrc}
                alt={revisedPrompt || trimmedPrompt || t("images.preview")}
                className="max-h-[64vh] max-w-full rounded-md object-contain"
              />
            ) : (
              <div className="flex flex-col items-center text-sm text-muted-foreground">
                <ImageIcon size={32} className="mb-2" />
                {t("images.emptyPreview")}
              </div>
            )}
          </div>

          {revisedPrompt ? (
            <div className="mt-4 rounded-md border bg-white p-3">
              <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
                {t("images.revisedPrompt")}
              </div>
              <p className="text-sm leading-6">{revisedPrompt}</p>
            </div>
          ) : null}

          {selectedJob?.references.length ? (
            <div className="mt-4">
              <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                {t("images.references")}
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {selectedJob.references.map((reference) => (
                  <div key={reference.id} className="overflow-hidden rounded-md border bg-white">
                    <img
                      src={reference.file_url}
                      alt={reference.original_file_name}
                      className="aspect-square w-full object-cover"
                    />
                    <div className="px-2 py-1.5 text-xs">
                      <div className="truncate font-semibold">{reference.original_file_name}</div>
                      <div className="text-muted-foreground">{formatBytes(reference.size_bytes)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
