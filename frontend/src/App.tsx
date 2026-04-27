import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { AppShell } from "@/app/AppShell";
import { useRoute } from "@/app/routing";
import { api } from "@/lib/api";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { SessionsPage } from "@/pages/SessionsPage";

function errorStatus(error: unknown) {
  return typeof error === "object" && error !== null && "status" in error
    ? Number((error as { status: number }).status)
    : 0;
}

export default function App() {
  const queryClient = useQueryClient();
  const { route, navigate } = useRoute();
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
        Loading
      </main>
    );
  }

  if (accounts.error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="max-w-md rounded-lg border bg-white p-5 text-sm shadow-soft">
          <h1 className="mb-2 text-lg font-bold">SwitchBoard</h1>
          <p className="text-destructive">{accounts.error.message}</p>
        </div>
      </main>
    );
  }

  return (
    <AppShell route={route} onNavigate={navigate}>
      {route.page === "sessions" ? (
        <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col overflow-hidden px-4 py-6">
          <SessionsPage selectedThreadId={route.threadId} onNavigate={navigate} />
        </div>
      ) : (
        <DashboardPage accounts={accounts.data ?? []} />
      )}
    </AppShell>
  );
}
