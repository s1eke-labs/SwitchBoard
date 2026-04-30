import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock3, Download, ImageIcon, Loader2, XCircle, WandSparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ImageGenerationJob, ImageGenerationRequest, ImageGenerationResponse } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { useI18n } from "@/i18n";
import type { TranslationKey } from "@/i18n";

const SIZE_OPTIONS = ["1024x1024", "1024x1536", "1536x1024", "auto"] as const;
const QUALITY_OPTIONS = ["auto", "low", "medium", "high"] as const;

type ImageSize = (typeof SIZE_OPTIONS)[number];
type ImageQuality = (typeof QUALITY_OPTIONS)[number];
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
  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState<ImageSize>("1024x1024");
  const [quality, setQuality] = useState<ImageQuality>("high");
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

  const createJob = useMutation({
    mutationFn: (payload: ImageGenerationRequest) => api.createImageJob(payload),
    onSuccess: (job) => {
      setSelectedJobId(job.id);
      queryClient.setQueryData<ImageGenerationJob[]>(["imageJobs"], (current) => [
        job,
        ...(current ?? []).filter((item) => item.id !== job.id),
      ]);
      toast.success(t("images.jobQueued"));
    },
    onError: (error) => {
      toast.error(t("images.generateFailed"), {
        description: formatAppError(error),
      });
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedPrompt || createJob.isPending) return;
    createJob.mutate({
      prompt: trimmedPrompt,
      size,
      quality,
      response_format: "b64_json",
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
        </CardContent>
      </Card>
    </div>
  );
}
