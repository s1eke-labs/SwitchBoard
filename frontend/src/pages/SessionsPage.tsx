import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Loader2, Search, UserRound } from "lucide-react";
import { api, SessionSummary } from "@/lib/api";
import { formatNumber, formatTime } from "@/lib/utils";
import { sessionPath } from "@/app/routing";
import { SessionEventList } from "@/features/sessions/SessionEventList";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

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
      className={`h-full min-h-0 w-full overflow-hidden border-b px-4 py-3 text-left transition-colors ${active ? "bg-blue-50" : "hover:bg-muted"}`}
    >
      <div className="line-clamp-2 max-w-full overflow-hidden break-all text-sm font-bold">{session.title}</div>
      <div className="mt-2 flex min-w-0 items-center gap-2 overflow-hidden text-xs text-muted-foreground">
        <span>{formatTime(session.updated_at)}</span>
        <span className="truncate">{session.model ?? session.model_provider}</span>
        <span className="shrink-0">{formatNumber(session.tokens_used)}</span>
      </div>
      <div className="mt-1 truncate text-xs text-muted-foreground">{session.cwd}</div>
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
  const [query, setQuery] = useState("");
  const [cursorStack, setCursorStack] = useState<Array<string | null>>([null]);
  const cursor = cursorStack[cursorStack.length - 1] ?? null;
  const page = cursorStack.length;
  const sessions = useQuery({
    queryKey: ["sessions", query, cursor],
    queryFn: () => api.sessions({ query, cursor, limit: SESSIONS_PAGE_SIZE }),
    placeholderData: (previousData) => previousData,
  });
  const sessionItems = sessions.data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((sessions.data?.total_count ?? 0) / SESSIONS_PAGE_SIZE));
  const emptySlots = Math.max(0, SESSIONS_PAGE_SIZE - sessionItems.length);
  const activeId = selectedThreadId ?? sessionItems[0]?.thread_id ?? null;
  const detail = useQuery({
    queryKey: ["session", activeId],
    queryFn: () => api.sessionDetail(activeId!),
    enabled: Boolean(activeId),
  });

  useEffect(() => {
    setCursorStack([null]);
  }, [query]);

  useEffect(() => {
    if (sessionItems[0] && (!selectedThreadId || !sessionItems.some((session) => session.thread_id === selectedThreadId))) {
      onNavigate(sessionPath(sessionItems[0].thread_id), true);
    }
  }, [onNavigate, selectedThreadId, sessionItems]);

  return (
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <UserRound size={20} />
          <h2 className="text-2xl font-bold">Sessions</h2>
        </div>
        <div className="relative w-full sm:w-80">
          <Search className="pointer-events-none absolute left-3 top-2.5 text-muted-foreground" size={16} />
          <Input className="pl-9" placeholder="Search sessions" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
      </div>
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[360px_1fr]">
        <Card className="flex min-h-0 flex-col overflow-hidden">
          {sessions.isPending ? (
            <div className="flex h-40 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 animate-spin" size={18} />
              Loading
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
                    <div className="flex h-full min-h-0 items-center border-b px-4 text-sm text-muted-foreground">No sessions on this page</div>
                    {Array.from({ length: SESSIONS_PAGE_SIZE - 1 }, (_, index) => (
                      <EmptySessionSlot key={`empty-page-${index}`} />
                    ))}
                  </div>
                )}
              </div>
              <div className="flex items-center justify-center border-t p-3">
                <div className="inline-flex items-center gap-1 rounded-md border bg-white p-1">
                  <Button
                    aria-label="Previous page"
                    title="Previous page"
                    variant="secondary"
                    size="icon"
                    onClick={() => setCursorStack((value) => (value.length > 1 ? value.slice(0, -1) : value))}
                    disabled={page === 1 || sessions.isFetching}
                  >
                    <ChevronLeft size={16} />
                  </Button>
                  <div className="h-9 min-w-24 px-3 text-center text-sm font-semibold leading-9 text-muted-foreground">
                    Page {Math.min(page, totalPages)} / {totalPages}
                  </div>
                  {sessions.data?.next_cursor ? (
                    <Button
                      aria-label="Next page"
                      title="Next page"
                      variant="secondary"
                      size="icon"
                      onClick={() => {
                        if (!sessions.data?.next_cursor) return;
                        setCursorStack((value) => [...value, sessions.data.next_cursor!]);
                      }}
                      disabled={sessions.isFetching}
                    >
                      <ChevronRight size={16} />
                    </Button>
                  ) : (
                    <Button aria-label="Next page" title="Next page" variant="secondary" size="icon" disabled>
                      <ChevronRight size={16} />
                    </Button>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="p-4 text-sm text-muted-foreground">No sessions</div>
          )}
        </Card>
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardHeader>
            <div className="min-w-0">
              <h3 className="truncate text-base font-bold">{detail.data?.summary.title ?? "Session detail"}</h3>
              <p className="truncate text-xs text-muted-foreground">{detail.data?.summary.cwd ?? ""}</p>
              {detail.data ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  {formatNumber(detail.data.event_count)} events from {formatNumber(detail.data.raw_event_count)} raw lines
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
