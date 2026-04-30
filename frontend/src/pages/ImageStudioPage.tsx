import { ChangeEvent, DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Clock3,
  Download,
  ImageIcon,
  Loader2,
  MessageSquare,
  Plus,
  Upload,
  X,
  XCircle,
  WandSparkles,
} from "lucide-react";
import { toast } from "sonner";
import { api, ImageConversation, ImageGenerationJob, ImageGenerationRequest, ImageGenerationResponse } from "@/lib/api";
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

function isActiveJob(job: ImageGenerationJob) {
  return job.status === "queued" || job.status === "running";
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

function formatConversationTime(value: number) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
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

function ConversationButton({
  conversation,
  active,
  onClick,
}: {
  conversation: ImageConversation;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
        active ? "border-primary bg-primary/5" : "bg-white hover:bg-muted"
      }`}
    >
      <span className="flex items-center gap-2">
        <MessageSquare size={15} className={active ? "text-primary" : "text-muted-foreground"} />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{conversation.title}</span>
      </span>
      <span className="mt-1 block truncate pl-6 text-xs text-muted-foreground">
        {formatConversationTime(conversation.updated_at)} · {conversation.job_count}
      </span>
    </button>
  );
}

function ImagePreviewModal({
  job,
  onClose,
}: {
  job: ImageGenerationJob;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const sources = imageSources(job.result);
  const revisedPrompt = job.result?.data.find((item) => item.revised_prompt)?.revised_prompt;
  const downloadSrc = sources[0] ?? null;

  function handleDownload() {
    if (!downloadSrc) return;
    const anchor = document.createElement("a");
    anchor.href = downloadSrc;
    anchor.download = `switchboard-image-${job.result?.created ?? job.updated_at}.png`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 sm:p-6">
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-md bg-background shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <JobStatusIcon job={job} />
            <span className="truncate text-sm font-semibold">{t(STATUS_LABEL_KEYS[job.status])}</span>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={!downloadSrc} onClick={handleDownload}>
              <Download size={15} />
              {t("images.download")}
            </Button>
            <button
              type="button"
              onClick={onClose}
              aria-label={t("images.closePreview")}
              className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="grid min-h-0 flex-1 gap-0 overflow-auto lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="flex min-h-[360px] items-center justify-center bg-muted p-4">
            {sources.length ? (
              <div className="grid max-h-full w-full grid-cols-1 gap-3 sm:grid-cols-2">
                {sources.map((src) => (
                  <img
                    key={src}
                    src={src}
                    alt={revisedPrompt || t("images.preview")}
                    className="max-h-[72vh] w-full rounded-md object-contain"
                  />
                ))}
              </div>
            ) : (
              <div className="flex items-center text-sm text-muted-foreground">
                <JobStatusIcon job={job} />
                <span className="ml-2">{t(STATUS_LABEL_KEYS[job.status])}</span>
              </div>
            )}
          </div>
          <div className="space-y-4 overflow-auto border-t p-4 lg:border-l lg:border-t-0">
            <div>
              <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{t("images.prompt")}</div>
              <p className="whitespace-pre-wrap text-sm leading-6">{job.prompt}</p>
            </div>
            {revisedPrompt ? (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
                  {t("images.revisedPrompt")}
                </div>
                <p className="whitespace-pre-wrap text-sm leading-6">{revisedPrompt}</p>
              </div>
            ) : null}
            {job.references.length ? (
              <div>
                <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{t("images.references")}</div>
                <div className="grid grid-cols-2 gap-2">
                  {job.references.map((reference) => (
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
            {job.error ? (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {job.error.message}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
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
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const trimmedPrompt = prompt.trim();

  const conversations = useQuery({
    queryKey: ["imageConversations"],
    queryFn: () => api.imageConversations(),
  });
  const activeConversation = useMemo(
    () => conversations.data?.find((conversation) => conversation.id === activeConversationId) ?? null,
    [activeConversationId, conversations.data],
  );
  const jobs = useQuery({
    queryKey: ["imageJobs", activeConversationId],
    enabled: Boolean(activeConversationId),
    queryFn: () => api.imageConversationJobs(activeConversationId!),
    refetchInterval: (query) => {
      const data = query.state.data as ImageGenerationJob[] | undefined;
      return data?.some(isActiveJob) ? 3000 : false;
    },
  });
  const selectedJob = useMemo(
    () => jobs.data?.find((job) => job.id === selectedJobId) ?? null,
    [jobs.data, selectedJobId],
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
    const items = conversations.data ?? [];
    if (items.length === 0) {
      setActiveConversationId(null);
      return;
    }
    if (!activeConversationId || !items.some((conversation) => conversation.id === activeConversationId)) {
      setActiveConversationId(items[0].id);
    }
  }, [activeConversationId, conversations.data]);

  const createConversation = useMutation({
    mutationFn: () => api.createImageConversation(),
    onSuccess: (conversation) => {
      setActiveConversationId(conversation.id);
      setSelectedJobId(null);
      queryClient.setQueryData<ImageConversation[]>(["imageConversations"], (current) => [
        conversation,
        ...(current ?? []).filter((item) => item.id !== conversation.id),
      ]);
    },
    onError: (error) => {
      toast.error(t("images.conversationCreateFailed"), {
        description: formatAppError(error),
      });
    },
  });

  const createJob = useMutation({
    mutationFn: (payload: ImageGenerationRequest) => api.createImageJob(payload),
    onSuccess: (job) => {
      const conversationId = job.conversation_id ?? activeConversationId;
      if (conversationId) {
        setActiveConversationId(conversationId);
        queryClient.setQueryData<ImageGenerationJob[]>(["imageJobs", conversationId], (current) => [
          ...((current ?? []).filter((item) => item.id !== job.id)),
          job,
        ]);
      }
      queryClient.invalidateQueries({ queryKey: ["imageConversations"] });
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedPrompt || createJob.isPending || createConversation.isPending) return;
    const references: ImageReferenceInput[] = referenceImages.map((reference) => ({
      file_name: reference.fileName,
      mime_type: reference.mimeType,
      b64_json: reference.b64Json,
    }));
    try {
      const conversationId = activeConversationId ?? (await createConversation.mutateAsync()).id;
      createJob.mutate({
        prompt: trimmedPrompt,
        size,
        quality,
        response_format: "b64_json",
        reference_images: references,
        conversation_id: conversationId,
      });
      setPrompt("");
    } catch {
      // 创建会话失败时，mutation 已经显示 toast。
    }
  }

  function selectConversation(conversationId: string) {
    setActiveConversationId(conversationId);
    setSelectedJobId(null);
  }

  return (
    <>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="min-h-0 overflow-hidden">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <WandSparkles size={18} className="text-primary" />
                <h2 className="text-base font-bold">{t("images.title")}</h2>
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => createConversation.mutate()}
                disabled={createConversation.isPending}
              >
                {createConversation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
                {t("images.newConversation")}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="flex max-h-[calc(100vh-9rem)] min-h-0 flex-col gap-5 overflow-auto">
            <div className="space-y-2">
              <div className="text-sm font-semibold">{t("images.conversations")}</div>
              <div className="space-y-2">
                {conversations.isPending ? (
                  <div className="flex h-10 items-center text-sm text-muted-foreground">
                    <Loader2 size={15} className="mr-2 animate-spin" />
                    {t("common.loading")}
                  </div>
                ) : (conversations.data ?? []).length ? (
                  (conversations.data ?? []).map((conversation) => (
                    <ConversationButton
                      key={conversation.id}
                      conversation={conversation}
                      active={conversation.id === activeConversationId}
                      onClick={() => selectConversation(conversation.id)}
                    />
                  ))
                ) : (
                  <div className="rounded-md border bg-white px-3 py-2 text-sm text-muted-foreground">
                    {t("images.noConversations")}
                  </div>
                )}
              </div>
            </div>

            <form className="space-y-5" onSubmit={handleSubmit}>
              <label className="block space-y-2">
                <span className="text-sm font-semibold">{t("images.prompt")}</span>
                <textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder={t("images.promptPlaceholder")}
                  className="min-h-32 w-full resize-y rounded-md border bg-white px-3 py-2 text-sm leading-6 outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>

              <div className="space-y-2">
                <span className="text-sm font-semibold">{t("images.size")}</span>
                <div className="flex flex-wrap gap-1 rounded-lg border bg-muted p-1">
                  {SIZE_OPTIONS.map((option) => (
                    <OptionButton key={option} active={size === option} label={option} onClick={() => setSize(option)} />
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
                            <img src={reference.previewUrl} alt={reference.fileName} className="h-full w-full object-cover" />
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

              <Button
                type="submit"
                className="w-full"
                disabled={!trimmedPrompt || createJob.isPending || createConversation.isPending}
              >
                {createJob.isPending || createConversation.isPending ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <WandSparkles size={16} />
                )}
                {createJob.isPending || createConversation.isPending ? t("images.queueing") : t("images.generate")}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="min-h-[520px] overflow-hidden">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <ImageIcon size={18} className="text-primary" />
                <h2 className="truncate text-base font-bold">{activeConversation?.title ?? t("images.preview")}</h2>
              </div>
            </div>
          </CardHeader>
          <CardContent className="flex min-h-[456px] flex-col">
            <div className="min-h-[456px] flex-1 overflow-auto rounded-md border bg-muted p-4">
              {jobs.isPending && activeConversationId ? (
                <div className="flex h-full min-h-[360px] items-center justify-center text-sm text-muted-foreground">
                  <Loader2 size={18} className="mr-2 animate-spin" />
                  {t("common.loading")}
                </div>
              ) : (jobs.data ?? []).length ? (
                <div className="flex flex-col gap-4">
                  {(jobs.data ?? []).map((job) => {
                    const sources = imageSources(job.result);
                    return (
                      <button
                        key={job.id}
                        type="button"
                        onClick={() => setSelectedJobId(job.id)}
                        className="ml-auto max-w-[78%] rounded-md border bg-white p-2 text-left shadow-soft transition-transform hover:-translate-y-0.5 hover:border-primary/40"
                      >
                        {sources.length ? (
                          <div className="grid grid-cols-2 gap-2">
                            {sources.slice(0, 4).map((src) => (
                              <img key={src} src={src} alt={t("images.preview")} className="h-28 w-full rounded object-cover" />
                            ))}
                          </div>
                        ) : (
                          <div className="flex h-28 w-40 items-center justify-center rounded bg-muted text-sm text-muted-foreground">
                            <JobStatusIcon job={job} />
                            <span className="ml-2">{t(STATUS_LABEL_KEYS[job.status])}</span>
                          </div>
                        )}
                        <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span className="flex min-w-0 items-center gap-1">
                            <JobStatusIcon job={job} />
                            <span className="truncate">{t(STATUS_LABEL_KEYS[job.status])}</span>
                          </span>
                          {job.position ? <span>{t("images.queuePosition", { position: job.position })}</span> : null}
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="flex h-full min-h-[360px] flex-col items-center justify-center text-sm text-muted-foreground">
                  <ImageIcon size={32} className="mb-2" />
                  {activeConversationId ? t("images.emptyConversation") : t("images.emptyPreview")}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {selectedJob ? <ImagePreviewModal job={selectedJob} onClose={() => setSelectedJobId(null)} /> : null}
    </>
  );
}
