import { ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, Image, LogOut, ReceiptText, Settings, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/heroui/button";
import { Spinner } from "@/components/heroui/spinner";
import { SegmentedControl } from "@/components/heroui/toggle-button-group";
import { Tooltip } from "@/components/heroui/tooltip";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { AppRoute } from "@/app/routing";
import { useI18n } from "@/i18n";

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
  const { t } = useI18n();
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const navItems = [
    { value: "dashboard", path: "/", label: <><BarChart3 size={16} />{t("nav.dashboard")}</> },
    { value: "sessions", path: "/sessions", label: <><UserRound size={16} />{t("nav.sessions")}</> },
    { value: "requestLogs", path: "/request-logs", label: <><ReceiptText size={16} />{t("nav.requestLogs")}</> },
    { value: "images", path: "/images", label: <><Image size={16} />{t("nav.images")}</> },
  ] as const;

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
                <p className="truncate text-xs text-muted-foreground">{t("app.subtitle")}</p>
              </div>
            </button>
            <SegmentedControl
              aria-label="SwitchBoard"
              value={route.page === "settings" ? null : route.page}
              options={navItems}
              onChange={(value) => {
                const item = navItems.find((navItem) => navItem.value === value);
                if (item) onNavigate(item.path);
              }}
            />
          </div>
          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            <Tooltip content={t("nav.settings")}>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("nav.settings")}
                onClick={() => onNavigate("/settings/dispatcher")}
              >
                <Settings size={18} />
              </Button>
            </Tooltip>
            <Tooltip content={t("nav.signOut")}>
              <Button variant="ghost" size="icon" aria-label={t("nav.signOut")} onClick={() => logout.mutate()} disabled={logout.isPending}>
                {logout.isPending ? <Spinner /> : <LogOut size={18} />}
              </Button>
            </Tooltip>
          </div>
        </div>
      </header>
      {children}
    </main>
  );
}
