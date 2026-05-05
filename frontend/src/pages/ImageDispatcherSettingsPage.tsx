import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "@heroui/react";
import { Pencil, PlugZap, Plus, RefreshCcw, Save, SquarePause, SquarePlay, Trash2 } from "lucide-react";
import { api, type ImageTaskDispatcherSettings } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { useI18n, type TranslationKey } from "@/i18n";
import { Alert } from "@/components/heroui/alert";
import { AlertDialog } from "@/components/heroui/alert-dialog";
import { Button } from "@/components/heroui/button";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { Input } from "@/components/heroui/input";
import { Spinner } from "@/components/heroui/spinner";

type DispatcherForm = {
  id: string | null;
  name: string;
  apiBaseUrl: string;
  token: string;
};

const emptyForm: DispatcherForm = {
  id: null,
  name: "",
  apiBaseUrl: "",
  token: "",
};

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
  const [form, setForm] = useState<DispatcherForm>(emptyForm);
  const [deleteTarget, setDeleteTarget] = useState<ImageTaskDispatcherSettings | null>(null);

  const dispatchers = useQuery({
    queryKey: ["imageTaskDispatchers"],
    queryFn: api.imageTaskDispatchers,
  });
  const workers = useQuery({
    queryKey: ["imageWorkerStatus"],
    queryFn: api.imageWorkerStatus,
    refetchInterval: 5000,
  });

  const dispatcherItems = useMemo(
    () => dispatchers.data?.items ?? workers.data?.dispatchers ?? [],
    [dispatchers.data?.items, workers.data?.dispatchers],
  );
  const editingDispatcher = useMemo(
    () => dispatcherItems.find((dispatcher) => dispatcher.id === form.id) ?? null,
    [dispatcherItems, form.id],
  );

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["imageTaskDispatchers"] });
    queryClient.invalidateQueries({ queryKey: ["imageTaskDispatcherSettings"] });
    queryClient.invalidateQueries({ queryKey: ["imageWorkerStatus"] });
  };

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name.trim(),
        api_base_url: form.apiBaseUrl.trim(),
        token: form.token.trim() || null,
      };
      return form.id ? api.updateImageTaskDispatcher(form.id, payload) : api.createImageTaskDispatcher(payload);
    },
    onSuccess: () => {
      setForm(emptyForm);
      invalidate();
      toast.success(t("dispatcher.saved"));
    },
    onError: (error) => toast.danger(t("dispatcher.saveFailed"), { description: formatAppError(error) }),
  });

  const test = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name.trim() || null,
        api_base_url: form.apiBaseUrl.trim() || null,
        token: form.token.trim() || null,
      };
      return form.id ? api.testNamedImageTaskDispatcher(form.id, payload) : api.testImageTaskDispatcher(payload);
    },
    onSuccess: () => toast.success(t("dispatcher.testOk")),
    onError: (error) => toast.danger(t("dispatcher.testFailed"), { description: formatAppError(error) }),
  });

  const register = useMutation({
    mutationFn: (dispatcherId: string) => api.registerNamedImageTaskDispatcher(dispatcherId),
    onSuccess: () => {
      invalidate();
      toast.success(t("dispatcher.registered"));
    },
    onError: (error) => toast.danger(t("dispatcher.registerFailed"), { description: formatAppError(error) }),
  });

  const pause = useMutation({
    mutationFn: (dispatcherId: string) => api.pauseNamedImageTaskDispatcher(dispatcherId),
    onSuccess: invalidate,
    onError: (error) => toast.danger(t("dispatcher.pauseFailed"), { description: formatAppError(error) }),
  });

  const resume = useMutation({
    mutationFn: (dispatcherId: string) => api.resumeNamedImageTaskDispatcher(dispatcherId),
    onSuccess: invalidate,
    onError: (error) => toast.danger(t("dispatcher.resumeFailed"), { description: formatAppError(error) }),
  });

  const remove = useMutation({
    mutationFn: (dispatcherId: string) => api.deleteImageTaskDispatcher(dispatcherId),
    onSuccess: () => {
      setDeleteTarget(null);
      invalidate();
      toast.success(t("dispatcher.deleted"));
    },
    onError: (error) => toast.danger(t("dispatcher.deleteFailed"), { description: formatAppError(error) }),
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.name.trim() || !form.apiBaseUrl.trim() || save.isPending) return;
    save.mutate();
  }

  function editDispatcher(dispatcher: ImageTaskDispatcherSettings) {
    setForm({
      id: dispatcher.id,
      name: dispatcher.name ?? "",
      apiBaseUrl: dispatcher.api_base_url ?? "",
      token: "",
    });
  }

  const actionBusy = test.isPending || register.isPending || pause.isPending || resume.isPending || remove.isPending;
  const submitDisabled = !form.name.trim() || !form.apiBaseUrl.trim() || save.isPending;
  const testDisabled = !form.name.trim() || !form.apiBaseUrl.trim() || (!form.id && !form.token.trim()) || test.isPending;

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
          <form className="grid gap-4" onSubmit={handleSubmit}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-semibold">
                {form.id ? t("dispatcher.editing", { name: editingDispatcher?.name ?? form.name }) : t("dispatcher.newDispatcher")}
              </div>
              {form.id ? (
                <Button type="button" variant="secondary" size="sm" onClick={() => setForm(emptyForm)}>
                  <Plus size={15} />
                  {t("dispatcher.addAnother")}
                </Button>
              ) : null}
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <label className="grid gap-1.5 text-sm font-semibold">
                {t("dispatcher.name")}
                <Input
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder={t("dispatcher.namePlaceholder")}
                />
              </label>
              <label className="grid gap-1.5 text-sm font-semibold md:col-span-2">
                {t("dispatcher.apiBaseUrl")}
                <Input
                  value={form.apiBaseUrl}
                  onChange={(event) => setForm((current) => ({ ...current, apiBaseUrl: event.target.value }))}
                  placeholder="https://scheduler.example.com/api"
                />
              </label>
            </div>
            <label className="grid gap-1.5 text-sm font-semibold">
              {t("dispatcher.token")}
              <Input
                type="password"
                value={form.token}
                onChange={(event) => setForm((current) => ({ ...current, token: event.target.value }))}
                placeholder={editingDispatcher?.token.configured ? editingDispatcher.token.preview ?? "********" : t("dispatcher.tokenPlaceholder")}
              />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={submitDisabled}>
                {save.isPending ? <Spinner /> : <Save size={16} />}
                {form.id ? t("dispatcher.update") : t("dispatcher.save")}
              </Button>
              <Button type="button" variant="secondary" disabled={testDisabled} onClick={() => test.mutate()}>
                {test.isPending ? <Spinner /> : <RefreshCcw size={16} />}
                {t("dispatcher.test")}
              </Button>
              <Button type="button" variant="secondary" disabled={save.isPending} onClick={() => setForm(emptyForm)}>
                <Plus size={16} />
                {t("dispatcher.clearForm")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-base font-bold">{t("dispatcher.systemStatus")}</h2>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-4">
          <div>{t("dispatcher.activeSlots")}: {workers.data?.active_worker_slots ?? 0}</div>
          <div>{t("dispatcher.activeLeases")}: {workers.data?.active_leases ?? 0}</div>
          <div>{t("dispatcher.queuedJobs")}: {workers.data?.queued_jobs ?? 0}</div>
          <div>{t("dispatcher.runningJobs")}: {workers.data?.running_jobs ?? 0}</div>
        </CardContent>
      </Card>

      {dispatchers.isPending ? (
        <Card>
          <CardContent>
            <div className="flex min-h-32 items-center justify-center text-sm text-muted-foreground">
              <Spinner className="mr-2" />
              {t("common.loading")}
            </div>
          </CardContent>
        </Card>
      ) : dispatchers.error ? (
        <Alert tone="danger">{formatAppError(dispatchers.error)}</Alert>
      ) : dispatcherItems.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">{t("dispatcher.empty")}</CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {dispatcherItems.map((dispatcher) => (
            <Card key={dispatcher.id}>
              <CardHeader className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-base font-bold">{dispatcher.name ?? t("dispatcher.untitled")}</div>
                  <div className="truncate text-xs text-muted-foreground">{dispatcher.api_base_url ?? t("common.notAvailable")}</div>
                </div>
                <span className={`rounded-md border px-2 py-1 text-xs font-bold ${statusTone(dispatcher.external_runner_status)}`}>
                  {t(`dispatcher.status.${dispatcher.external_runner_status}` as TranslationKey)}
                </span>
              </CardHeader>
              <CardContent className="grid gap-3 text-sm">
                <div className="grid gap-2 md:grid-cols-3">
                  <div>{t("dispatcher.runnerId")}: {dispatcher.external_runner_id ?? t("common.notAvailable")}</div>
                  <div>{t("dispatcher.lastHeartbeat")}: {formatTime(dispatcher.external_last_heartbeat_at)}</div>
                  <div>{t("dispatcher.lastClaim")}: {formatTime(dispatcher.external_last_claim_at)}</div>
                  <div>{t("dispatcher.taskCount")}: {dispatcher.task_count}</div>
                  <div>{t("dispatcher.tokenStatus")}: {dispatcher.token.configured ? dispatcher.token.preview ?? "********" : t("common.notAvailable")}</div>
                </div>
                <div className="grid gap-2">
                  <div className="font-semibold">{t("dispatcher.currentTask")}</div>
                  {dispatcher.running_external_tasks.length === 0 ? (
                    <div className="text-muted-foreground">{t("dispatcher.noRunningTask")}</div>
                  ) : (
                    <div className="grid gap-1.5">
                      {dispatcher.running_external_tasks.map((task) => (
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
                {dispatcher.external_last_error ? <Alert tone="danger">{dispatcher.external_last_error}</Alert> : null}
                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" variant="secondary" disabled={actionBusy} onClick={() => editDispatcher(dispatcher)}>
                    <Pencil size={16} />
                    {t("dispatcher.edit")}
                  </Button>
                  <Button type="button" variant="secondary" disabled={actionBusy || !dispatcher.configured} onClick={() => register.mutate(dispatcher.id)}>
                    {register.isPending ? <Spinner /> : <RefreshCcw size={16} />}
                    {t("dispatcher.register")}
                  </Button>
                  {dispatcher.paused ? (
                    <Button type="button" variant="secondary" disabled={actionBusy || !dispatcher.configured} onClick={() => resume.mutate(dispatcher.id)}>
                      {resume.isPending ? <Spinner /> : <SquarePlay size={16} />}
                      {t("dispatcher.resume")}
                    </Button>
                  ) : (
                    <Button type="button" variant="secondary" disabled={actionBusy || !dispatcher.configured} onClick={() => pause.mutate(dispatcher.id)}>
                      {pause.isPending ? <Spinner /> : <SquarePause size={16} />}
                      {t("dispatcher.pause")}
                    </Button>
                  )}
                  <Button type="button" variant="destructive" disabled={actionBusy} onClick={() => setDeleteTarget(dispatcher)}>
                    <Trash2 size={16} />
                    {t("dispatcher.delete")}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {deleteTarget ? (
        <AlertDialog.Backdrop isOpen onOpenChange={(open) => { if (!open && !remove.isPending) setDeleteTarget(null); }}>
          <AlertDialog.Container>
            <AlertDialog.Dialog>
              <AlertDialog.Header>
                <AlertDialog.Icon status="danger" />
                <AlertDialog.Heading>{t("dispatcher.deleteConfirmTitle")}</AlertDialog.Heading>
              </AlertDialog.Header>
              <AlertDialog.Body>{t("dispatcher.deleteConfirm", { name: deleteTarget.name ?? t("dispatcher.untitled") })}</AlertDialog.Body>
              <AlertDialog.Footer>
                <Button type="button" variant="secondary" disabled={remove.isPending} onClick={() => setDeleteTarget(null)}>
                  {t("common.cancel")}
                </Button>
                <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(deleteTarget.id)}>
                  {remove.isPending ? <Spinner /> : <Trash2 size={15} />}
                  {t("dispatcher.delete")}
                </Button>
              </AlertDialog.Footer>
            </AlertDialog.Dialog>
          </AlertDialog.Container>
        </AlertDialog.Backdrop>
      ) : null}
    </div>
  );
}
