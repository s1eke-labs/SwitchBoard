import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search, UserRound } from "lucide-react";
import { api, SessionSummary } from "@/lib/api";
import { useI18n } from "@/i18n";
import { cn, formatNumber, formatTime } from "@/lib/utils";
import { sessionPath } from "@/app/routing";
import { SessionEventList } from "@/features/sessions/SessionEventList";
import { PageSelector } from "@/components/PageSelector";
import { Card, CardHeader } from "@/components/heroui/card";
import { Input } from "@/components/heroui/input";

const SESSIONS_PAGE_SIZE = 7;

function SessionButton({
  session,
  active,
  onClick,
}: {
  session: SessionSummary;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "h-full min-h-0 w-full overflow-hidden border-b px-4 py-4 text-left transition-colors last:border-b-0",
        active ? "bg-blue-50/80" : "bg-white hover:bg-muted/50",
      )}
    >
      <div className="line-clamp-2 max-w-full overflow-hidden break-all text-sm font-bold leading-5 text-foreground">
        {session.title}
      </div>
      <div className="mt-2 flex min-w-0 items-center gap-1.5 overflow-hidden text-xs text-muted-foreground">
        <span>{formatTime(session.updated_at)}</span>
        <span aria-hidden="true">·</span>
        <span className="truncate">{session.model ?? session.model_provider}</span>
        <span aria-hidden="true">·</span>
        <span className="shrink-0">{formatNumber(session.tokens_used)}</span>
      </div>
      <div className="mt-1.5 truncate text-xs text-muted-foreground">{session.cwd}</div>
    </button>
  );
}

function EmptySessionSlot() {
  return <div className="h-full min-h-0 border-b" aria-hidden="true" />;
}

export function SessionsPage({
  selectedThreadId,
  onNavigate,
}: {
  selectedThreadId: string | null;
  onNavigate: (path: string, replace?: boolean) => void;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const sessions = useQuery({
    queryKey: ["sessions", query, page],
    queryFn: () => api.sessions({ query, page, limit: SESSIONS_PAGE_SIZE }),
    placeholderData: (previousData) => previousData,
  });
  const sessionItems = useMemo(() => sessions.data?.items ?? [], [sessions.data?.items]);
  const totalPages = Math.max(1, Math.ceil((sessions.data?.total_count ?? 0) / SESSIONS_PAGE_SIZE));
  const emptySlots = Math.max(0, SESSIONS_PAGE_SIZE - sessionItems.length);
  const activeId = selectedThreadId ?? sessionItems[0]?.thread_id ?? null;
  const detail = useQuery({
    queryKey: ["session", activeId],
    queryFn: () => api.sessionDetail(activeId!),
    enabled: Boolean(activeId),
  });

  useEffect(() => {
    setPage(1);
  }, [query]);

  useEffect(() => {
    if (!sessions.isFetching && sessions.data?.total_count && page > totalPages) {
      setPage(totalPages);
    }
  }, [page, sessions.data?.total_count, sessions.isFetching, totalPages]);

  useEffect(() => {
    if (sessionItems[0] && (!selectedThreadId || !sessionItems.some((session) => session.thread_id === selectedThreadId))) {
      onNavigate(sessionPath(sessionItems[0].thread_id), true);
    }
  }, [onNavigate, selectedThreadId, sessionItems]);

  function selectPage(targetPage: number) {
    if (targetPage === page || targetPage < 1 || targetPage > totalPages || sessions.isFetching) return;
    setPage(targetPage);
  }

  return (
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="flex items-center gap-2">
          <UserRound size={20} strokeWidth={1.8} />
          <h2 className="text-2xl font-bold leading-tight">{t("sessions.title")}</h2>
        </div>
        <div className="relative w-full sm:w-96">
          <Search className="pointer-events-none absolute left-3 top-2.5 text-muted-foreground" size={16} />
          <Input
            className="h-10 rounded-lg pl-9 text-sm"
            placeholder={t("sessions.searchPlaceholder")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>
      <div className="grid min-h-0 flex-1 gap-5 xl:grid-cols-[365px_minmax(0,1fr)]">
        <Card className="flex min-h-[380px] flex-col overflow-hidden rounded-lg shadow-none">
          {sessions.isPending ? (
            <div className="flex h-40 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 animate-spin" size={18} />
              {t("common.loading")}
            </div>
          ) : sessionItems.length || page > 1 ? (
            <>
              <div className="min-h-0 flex-1 overflow-hidden">
                {sessionItems.length ? (
                  <div
                    className={`grid h-full min-h-0 transition-opacity ${sessions.isFetching ? "opacity-70" : ""}`}
                    style={{ gridTemplateRows: `repeat(${SESSIONS_PAGE_SIZE}, minmax(0, 1fr))` }}
                  >
                    {sessionItems.map((session) => (
                      <SessionButton
                        key={session.thread_id}
                        session={session}
                        active={session.thread_id === activeId}
                        onClick={() => onNavigate(sessionPath(session.thread_id))}
                      />
                    ))}
                    {Array.from({ length: emptySlots }, (_, index) => (
                      <EmptySessionSlot key={`empty-${index}`} />
                    ))}
                  </div>
                ) : (
                  <div
                    className="grid h-full min-h-0"
                    style={{ gridTemplateRows: `repeat(${SESSIONS_PAGE_SIZE}, minmax(0, 1fr))` }}
                  >
                    <div className="flex h-full min-h-0 items-center border-b px-4 text-sm text-muted-foreground">{t("sessions.noSessionsOnPage")}</div>
                    {Array.from({ length: SESSIONS_PAGE_SIZE - 1 }, (_, index) => (
                      <EmptySessionSlot key={`empty-page-${index}`} />
                    ))}
                  </div>
                )}
              </div>
              <div className="flex items-center justify-center border-t p-3">
                <PageSelector
                  page={page}
                  totalPages={totalPages}
                  disabled={sessions.isFetching}
                  jumping={sessions.isFetching}
                  onSelect={selectPage}
                />
              </div>
            </>
          ) : (
            <div className="p-4 text-sm text-muted-foreground">{t("sessions.noSessions")}</div>
          )}
        </Card>
        <Card className="flex min-h-0 flex-col overflow-hidden rounded-lg shadow-none">
          <CardHeader className="px-5 py-4">
            <div className="min-w-0">
              <h3 className="truncate text-base font-bold leading-6">{detail.data?.summary.title ?? t("sessions.sessionDetail")}</h3>
              <p className="mt-1 truncate text-xs text-muted-foreground">{detail.data?.summary.cwd ?? ""}</p>
              {detail.data ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("sessions.eventsFromRaw", {
                    eventCount: formatNumber(detail.data.event_count),
                    rawCount: formatNumber(detail.data.raw_event_count),
                  })}
                </p>
              ) : null}
            </div>
          </CardHeader>
          <SessionEventList activeId={activeId} detailPending={detail.isPending} totalEventCount={detail.data?.event_count ?? null} />
        </Card>
      </div>
    </section>
  );
}
