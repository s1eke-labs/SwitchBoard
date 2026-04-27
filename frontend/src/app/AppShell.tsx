import { ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, LogOut, ReceiptText, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AppRoute } from "@/app/routing";

function NavButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex h-8 items-center gap-2 rounded-md px-2.5 text-sm font-semibold transition-colors ${
        active ? "bg-foreground text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

export function AppShell({
  route,
  onNavigate,
  children,
}: {
  route: AppRoute;
  onNavigate: (path: string, replace?: boolean) => void;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  return (
    <main className="flex h-screen flex-col overflow-hidden bg-background">
      <header className="shrink-0 border-b bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <button
              onClick={() => onNavigate("/")}
              className="flex min-w-0 items-center gap-2.5 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-foreground text-white">
                <Activity size={18} />
              </div>
              <div className="min-w-0">
                <h1 className="truncate text-lg font-bold leading-5">SwitchBoard</h1>
                <p className="truncate text-xs text-muted-foreground">Local Codex console</p>
              </div>
            </button>
            <div className="flex items-center gap-1">
              <NavButton active={route.page === "dashboard"} onClick={() => onNavigate("/")}>
                <BarChart3 size={16} />
                Dashboard
              </NavButton>
              <NavButton active={route.page === "sessions"} onClick={() => onNavigate("/sessions")}>
                <UserRound size={16} />
                Sessions
              </NavButton>
              <NavButton active={route.page === "requestLogs"} onClick={() => onNavigate("/request-logs")}>
                <ReceiptText size={16} />
                Request Logs
              </NavButton>
            </div>
          </div>
          <Button variant="ghost" size="icon" title="Sign out" aria-label="Sign out" onClick={() => logout.mutate()}>
            <LogOut size={18} />
          </Button>
        </div>
      </header>
      {children}
    </main>
  );
}
