import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/app/AppShell";
import { useRoute } from "@/app/routing";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import type { ImageGenerationJob } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { DashboardPage } from "@/pages/DashboardPage";
import { ImageStudioPage } from "@/pages/ImageStudioPage";
import { LoginPage } from "@/pages/LoginPage";
import { RequestLogsPage } from "@/pages/RequestLogsPage";
import { SessionsPage } from "@/pages/SessionsPage";

function errorStatus(error: unknown) {
  return typeof error === "object" && error !== null && "status" in error
    ? Number((error as { status: number }).status)
    : 0;
}

function isActiveImageJob(job: ImageGenerationJob) {
  return job.status === "queued" || job.status === "running";
}

function ImageJobNotifier() {
  const { t } = useI18n();
  const statusesRef = useRef(new Map<string, ImageGenerationJob["status"]>());
  const jobs = useQuery({
    queryKey: ["imageJobs"],
    queryFn: () => api.imageJobs(),
    refetchInterval: (query) => {
      const data = query.state.data as ImageGenerationJob[] | undefined;
      return data?.some(isActiveImageJob) ? 3000 : false;
    },
  });

  useEffect(() => {
    for (const job of jobs.data ?? []) {
      const previous = statusesRef.current.get(job.id);
      if (previous && previous !== job.status && job.status === "succeeded") {
        toast.success(t("images.generated"));
      }
      if (previous && previous !== job.status && job.status === "failed") {
        toast.error(t("images.generateFailed"), {
          description: job.error?.message,
        });
      }
      statusesRef.current.set(job.id, job.status);
    }
  }, [jobs.data, t]);

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

  if (accounts.error && errorStatus(accounts.error) === 401) {
    return <LoginPage onDone={() => queryClient.invalidateQueries({ queryKey: ["accounts"] })} />;
  }

  if (accounts.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        <Loader2 className="mr-2 animate-spin" size={18} />
        {t("common.loading")}
      </main>
    );
  }

  if (accounts.error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="max-w-md rounded-lg border bg-white p-5 text-sm shadow-soft">
          <h1 className="mb-2 text-lg font-bold">SwitchBoard</h1>
          <p className="text-destructive">{formatAppError(accounts.error)}</p>
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
      ) : (
        <DashboardPage accounts={accounts.data ?? []} />
      )}
    </AppShell>
  );
}
