import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "@heroui/react";
import { PlugZap, RefreshCcw, Send, SquarePause, SquarePlay } from "lucide-react";
import { api, type ImageTaskDispatcherSettings } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { useI18n, type TranslationKey } from "@/i18n";
import { Alert } from "@/components/heroui/alert";
import { Button } from "@/components/heroui/button";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { Input } from "@/components/heroui/input";
import { Spinner } from "@/components/heroui/spinner";

function formatTime(value: number | null) {
  if (!value) return "n/a";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}

function statusTone(status: ImageTaskDispatcherSettings["external_runner_status"]) {
  if (status === "online") return "text-emerald-700 bg-emerald-50 border-emerald-200";
  if (status === "paused" || status === "unconfigured") return "text-muted-foreground bg-muted border-border";
  return "text-destructive bg-red-50 border-red-200";
}

export function ImageDispatcherSettingsPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["imageTaskDispatcherSettings"],
    queryFn: api.imageTaskDispatcherSettings,
  });
  const workers = useQuery({
    queryKey: ["imageWorkerStatus"],
    queryFn: api.imageWorkerStatus,
    refetchInterval: 5000,
  });
  const [name, setName] = useState("");
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [token, setToken] = useState("");

  useEffect(() => {
    if (!settings.data) return;
    setName(settings.data.name ?? "");
    setApiBaseUrl(settings.data.api_base_url ?? "");
    setToken("");
  }, [settings.data]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["imageTaskDispatcherSettings"] });
    queryClient.invalidateQueries({ queryKey: ["imageWorkerStatus"] });
  };

  const save = useMutation({
    mutationFn: () =>
      api.saveImageTaskDispatcherSettings({
        name: name.trim(),
        api_base_url: apiBaseUrl.trim(),
        token: token.trim() || null,
      }),
    onSuccess: () => {
      setToken("");
      invalidate();
      toast.success(t("dispatcher.saved"));
    },
    onError: (error) => toast.danger(t("dispatcher.saveFailed"), { description: formatAppError(error) }),
  });

  const test = useMutation({
    mutationFn: () =>
      api.testImageTaskDispatcher({
        name: name.trim() || null,
        api_base_url: apiBaseUrl.trim() || null,
        token: token.trim() || null,
      }),
    onSuccess: () => toast.success(t("dispatcher.testOk")),
    onError: (error) => toast.danger(t("dispatcher.testFailed"), { description: formatAppError(error) }),
  });

  const register = useMutation({
    mutationFn: api.registerImageTaskDispatcher,
    onSuccess: () => {
      invalidate();
      toast.success(t("dispatcher.registered"));
    },
    onError: (error) => toast.danger(t("dispatcher.registerFailed"), { description: formatAppError(error) }),
  });

  const pause = useMutation({
    mutationFn: api.pauseImageTaskDispatcher,
    onSuccess: invalidate,
    onError: (error) => toast.danger(t("dispatcher.pauseFailed"), { description: formatAppError(error) }),
  });

  const resume = useMutation({
    mutationFn: api.resumeImageTaskDispatcher,
    onSuccess: invalidate,
    onError: (error) => toast.danger(t("dispatcher.resumeFailed"), { description: formatAppError(error) }),
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !apiBaseUrl.trim() || save.isPending) return;
    save.mutate();
  }

  const current = settings.data;
  const runningExternalTasks = workers.data?.running_external_tasks ?? [];
  const busy = save.isPending || test.isPending || register.isPending || pause.isPending || resume.isPending;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <PlugZap size={18} className="text-primary" />
            <h1 className="text-base font-bold">{t("dispatcher.title")}</h1>
          </div>
        </CardHeader>
        <CardContent>
          {settings.isPending ? (
            <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
              <Spinner className="mr-2" />
              {t("common.loading")}
            </div>
          ) : settings.error ? (
            <Alert tone="danger">{formatAppError(settings.error)}</Alert>
          ) : (
            <form className="grid gap-4" onSubmit={handleSubmit}>
              <div className="grid gap-3 md:grid-cols-3">
                <label className="grid gap-1.5 text-sm font-semibold">
                  {t("dispatcher.name")}
                  <Input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("dispatcher.namePlaceholder")} />
                </label>
                <label className="grid gap-1.5 text-sm font-semibold md:col-span-2">
                  {t("dispatcher.apiBaseUrl")}
                  <Input
                    value={apiBaseUrl}
                    onChange={(event) => setApiBaseUrl(event.target.value)}
                    placeholder="https://scheduler.example.com/api"
                  />
                </label>
              </div>
              <label className="grid gap-1.5 text-sm font-semibold">
                {t("dispatcher.token")}
                <Input
                  type="password"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  placeholder={current?.token.configured ? current.token.preview ?? "********" : t("dispatcher.tokenPlaceholder")}
                />
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" disabled={!name.trim() || !apiBaseUrl.trim() || save.isPending}>
                  {save.isPending ? <Spinner /> : <Send size={16} />}
                  {t("dispatcher.save")}
                </Button>
                <Button type="button" variant="secondary" disabled={busy} onClick={() => test.mutate()}>
                  {test.isPending ? <Spinner /> : <RefreshCcw size={16} />}
                  {t("dispatcher.test")}
                </Button>
                <Button type="button" variant="secondary" disabled={busy} onClick={() => register.mutate()}>
                  {register.isPending ? <Spinner /> : <RefreshCcw size={16} />}
                  {t("dispatcher.register")}
                </Button>
                {current?.paused ? (
                  <Button type="button" variant="secondary" disabled={busy} onClick={() => resume.mutate()}>
                    {resume.isPending ? <Spinner /> : <SquarePlay size={16} />}
                    {t("dispatcher.resume")}
                  </Button>
                ) : (
                  <Button type="button" variant="secondary" disabled={busy || !current?.configured} onClick={() => pause.mutate()}>
                    {pause.isPending ? <Spinner /> : <SquarePause size={16} />}
                    {t("dispatcher.pause")}
                  </Button>
                )}
              </div>
            </form>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-base font-bold">{t("dispatcher.status")}</h2>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-md border px-2 py-1 text-xs font-bold ${statusTone(current?.external_runner_status ?? "unconfigured")}`}>
              {t(`dispatcher.status.${current?.external_runner_status ?? "unconfigured"}` as TranslationKey)}
            </span>
            <span className="text-muted-foreground">
              {t("dispatcher.runnerId")}: {current?.external_runner_id ?? t("common.notAvailable")}
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-3">
            <div>{t("dispatcher.lastHeartbeat")}: {formatTime(current?.external_last_heartbeat_at ?? null)}</div>
            <div>{t("dispatcher.lastClaim")}: {formatTime(current?.external_last_claim_at ?? null)}</div>
            <div>{t("dispatcher.activeSlots")}: {workers.data?.active_worker_slots ?? 0}</div>
            <div>{t("dispatcher.queuedJobs")}: {workers.data?.queued_jobs ?? 0}</div>
            <div>{t("dispatcher.runningJobs")}: {workers.data?.running_jobs ?? 0}</div>
          </div>
          <div className="grid gap-2">
            <div className="font-semibold">{t("dispatcher.currentTask")}</div>
            {runningExternalTasks.length === 0 ? (
              <div className="text-muted-foreground">{t("dispatcher.noRunningTask")}</div>
            ) : (
              <div className="grid gap-1.5">
                {runningExternalTasks.map((task) => (
                  <div key={task.id} className="grid gap-1 md:grid-cols-[minmax(0,220px)_auto_minmax(0,1fr)] md:items-center md:gap-3">
                    <span className="truncate font-mono text-xs" title={task.source_task_id ?? task.id}>
                      {task.source_task_id ?? task.id}
                    </span>
                    <span className="text-xs font-semibold text-primary">
                      {t((task.status === "leased" ? "dispatcher.taskStatus.leased" : "dispatcher.taskStatus.running") as TranslationKey)}
                    </span>
                    <span className="truncate text-muted-foreground" title={task.prompt}>
                      {task.prompt}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
          {current?.external_last_error ? <Alert tone="danger">{current.external_last_error}</Alert> : null}
        </CardContent>
      </Card>
    </div>
  );
}
