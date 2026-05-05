import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "@heroui/react";
import { AppShell } from "@/app/AppShell";
import { useRoute } from "@/app/routing";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import type { ImageGenerationJobStatusSummary } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { DashboardPage } from "@/pages/DashboardPage";
import { ImageStudioPage } from "@/pages/ImageStudioPage";
import { LoginPage } from "@/pages/LoginPage";
import { RequestLogsPage } from "@/pages/RequestLogsPage";
import { SessionsPage } from "@/pages/SessionsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { Alert } from "@/components/heroui/alert";
import { Spinner } from "@/components/heroui/spinner";

function errorStatus(error: unknown) {
  return typeof error === "object" && error !== null && "status" in error
    ? Number((error as { status: number }).status)
    : 0;
}

function ImageJobNotifier() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const statusesRef = useRef(new Map<string, ImageGenerationJobStatusSummary["status"]>());
  const trackedJobIdsRef = useRef(new Set<string>());
  const hasSeenInitialStatusesRef = useRef(false);
  const jobs = useQuery({
    queryKey: ["imageJobStatuses", "notifier"],
    queryFn: () => api.imageJobStatuses({ ids: [...trackedJobIdsRef.current] }),
    refetchInterval: (query) => {
      return query.state.data?.active_count ? 3000 : false;
    },
  });

  useEffect(() => {
    const hasSeenInitialStatuses = hasSeenInitialStatusesRef.current;
    let shouldRefreshGallery = false;
    for (const job of jobs.data?.items ?? []) {
      const previous = statusesRef.current.get(job.id);
      const isActive = job.status === "queued" || job.status === "running";
      if (isActive) {
        trackedJobIdsRef.current.add(job.id);
      } else {
        trackedJobIdsRef.current.delete(job.id);
      }
      if (previous && previous !== job.status) {
        shouldRefreshGallery = true;
        if (job.status === "succeeded") {
          toast.success(t("images.generated"));
        }
        if (job.status === "failed" && job.error?.code !== "IMAGE_JOB_STOPPED") {
          toast.danger(t("images.generateFailed"), {
            description: job.error?.message,
          });
        }
      }
      if (!previous && hasSeenInitialStatuses) {
        shouldRefreshGallery = true;
      }
      statusesRef.current.set(job.id, job.status);
    }
    if (jobs.data) {
      hasSeenInitialStatusesRef.current = true;
    }
    if (shouldRefreshGallery) {
      queryClient.invalidateQueries({ queryKey: ["imageGallery"] });
    }
  }, [jobs.data, queryClient, t]);

  return null;
}

export default function App() {
  const queryClient = useQueryClient();
  const { route, navigate } = useRoute();
  const { t } = useI18n();
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: api.accounts,
  });

  useEffect(() => {
    if (window.location.pathname === "/images/dispatcher") {
      navigate("/settings/dispatcher", true);
    }
  }, [navigate]);

  if (accounts.error && errorStatus(accounts.error) === 401) {
    return <LoginPage onDone={() => queryClient.invalidateQueries({ queryKey: ["accounts"] })} />;
  }

  if (accounts.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        <Spinner className="mr-2" />
        {t("common.loading")}
      </main>
    );
  }

  if (accounts.error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="max-w-md rounded-lg border bg-white p-5 text-sm shadow-soft">
          <h1 className="mb-2 text-lg font-bold">SwitchBoard</h1>
          <Alert tone="danger">{formatAppError(accounts.error)}</Alert>
        </div>
      </main>
    );
  }

  return (
    <AppShell route={route} onNavigate={navigate}>
      <ImageJobNotifier />
      {route.page === "sessions" ? (
        <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col overflow-hidden px-4 py-6">
          <SessionsPage selectedThreadId={route.threadId} onNavigate={navigate} />
        </div>
      ) : route.page === "requestLogs" ? (
        <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col overflow-hidden px-4 py-6">
          <RequestLogsPage accounts={accounts.data ?? []} />
        </div>
      ) : route.page === "images" ? (
        <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col overflow-auto px-4 py-6">
          <ImageStudioPage />
        </div>
      ) : route.page === "settings" ? (
        <div className="mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col overflow-auto px-4 py-6">
          <SettingsPage section={route.section} onNavigate={navigate} />
        </div>
      ) : (
        <DashboardPage accounts={accounts.data ?? []} />
      )}
    </AppShell>
  );
}
