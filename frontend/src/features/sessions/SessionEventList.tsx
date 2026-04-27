import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { api, SessionEventPreview, SessionUserIndexItem } from "@/lib/api";
import { cn, formatNumber, formatTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatBytes, fullEventBody, userIndexLabel } from "@/features/sessions/sessionUtils";

const SESSION_EVENTS_PAGE_SIZE = 80;

type SessionEventDisplayRole = "user" | "assistant" | "system";

const eventDisplayStyles: Record<
  SessionEventDisplayRole,
  {
    label: string;
    avatar: string;
    badgeTone: "blue" | "green" | "neutral";
    avatarClassName: string;
    panelClassName: string;
  }
> = {
  user: {
    label: "user",
    avatar: "U",
    badgeTone: "blue",
    avatarClassName: "bg-blue-600 text-white shadow-blue-100",
    panelClassName: "border-blue-200 bg-blue-50/80",
  },
  assistant: {
    label: "assistant",
    avatar: "A",
    badgeTone: "green",
    avatarClassName: "bg-emerald-600 text-white shadow-emerald-100",
    panelClassName: "border-emerald-200 bg-emerald-50/70",
  },
  system: {
    label: "system",
    avatar: "S",
    badgeTone: "neutral",
    avatarClassName: "bg-muted-foreground text-white",
    panelClassName: "border-border bg-white",
  },
};

function sessionEventDisplayRole(kind: string): SessionEventDisplayRole {
  if (kind === "user") return "user";
  if (kind === "assistant") return "assistant";
  return "system";
}

function EventRow({ event, threadId, focused }: { event: SessionEventPreview; threadId: string; focused?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const title = event.name ?? event.title ?? event.kind;
  const displayRole = sessionEventDisplayRole(event.kind);
  const display = eventDisplayStyles[displayRole];
  const isSystem = displayRole === "system";
  const sizeLabel = formatBytes(event.body_bytes);
  const timeLabel = event.timestamp ? formatTime(Date.parse(event.timestamp) / 1000) : "";
  const fullEvent = useQuery({
    queryKey: ["session-event", threadId, event.line_no],
    queryFn: () => api.sessionEvent(threadId, event.line_no),
    enabled: expanded && event.body_truncated,
    staleTime: Infinity,
  });
  const body = expanded && fullEvent.data ? fullEventBody(fullEvent.data) : event.body_preview;
  const hasBody = event.body_bytes > 0 || event.body_preview.trim().length > 0;
  const canExpand = isSystem ? hasBody || event.body_truncated : event.body_truncated;

  if (isSystem) {
    return (
      <div className="px-4 py-1">
        <div className="flex justify-center text-center">
          <div className="w-full max-w-2xl">
            <button
              type="button"
              className={cn(
                "inline-flex max-w-full min-w-0 flex-wrap items-center justify-center gap-x-1 gap-y-0 rounded-full px-2 py-0 text-[10px] leading-4 text-muted-foreground transition-colors",
                canExpand ? "cursor-pointer hover:text-foreground" : "cursor-default",
                expanded ? "bg-muted/60 text-foreground" : "bg-muted/25",
                focused ? "ring-2 ring-ring" : "",
              )}
              onClick={() => {
                if (canExpand) setExpanded((value) => !value);
              }}
              aria-expanded={canExpand ? expanded : undefined}
            >
              {canExpand ? expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} /> : null}
              <span>{title}</span>
              <span>line {event.line_no}</span>
              {timeLabel ? <span>{timeLabel}</span> : null}
              {event.body_bytes > 0 ? <span>{sizeLabel}</span> : null}
            </button>
            {expanded ? (
              <div className="mt-2 rounded-md border bg-muted/20 px-3.5 py-3 text-left">
                {body ? <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-foreground">{body}</pre> : null}
                <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
                  {event.body_truncated && fullEvent.isFetching ? (
                    <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Loader2 className="animate-spin" size={10} />
                      Loading
                    </span>
                  ) : null}
                  {fullEvent.error ? <span className="text-[10px] text-destructive">{fullEvent.error.message}</span> : null}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 py-3">
      <div className="flex w-full items-start gap-3">
        <div
          className={cn(
            "mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold shadow-sm",
            display.avatarClassName,
          )}
          aria-hidden="true"
        >
          {display.avatar}
        </div>
        <article
          className={cn(
            "min-w-0 flex-1 rounded-lg border px-3.5 py-3 shadow-soft transition-shadow",
            display.panelClassName,
            focused ? "ring-2 ring-ring" : "",
          )}
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Badge tone={display.badgeTone}>{display.label}</Badge>
              <span className="text-xs font-medium text-muted-foreground">line {event.line_no}</span>
              {canExpand ? <span className="text-xs text-muted-foreground">{sizeLabel}</span> : null}
            </div>
            {timeLabel ? <span className="text-xs text-muted-foreground">{timeLabel}</span> : null}
          </div>
          {body ? <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-foreground">{body}</pre> : null}
          {canExpand ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                {expanded ? "Collapse" : "Load full"} - {sizeLabel}
              </Button>
              {fullEvent.isFetching ? (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="animate-spin" size={12} />
                  Loading
                </span>
              ) : null}
              {fullEvent.error ? <span className="text-xs text-destructive">{fullEvent.error.message}</span> : null}
            </div>
          ) : null}
        </article>
      </div>
    </div>
  );
}

function SessionUserDirectory({
  items,
  loading,
  error,
  activeLineNo,
  pendingEventIndex,
  onJump,
}: {
  items: SessionUserIndexItem[];
  loading: boolean;
  error: unknown;
  activeLineNo: number | null;
  pendingEventIndex: number | null;
  onJump: (item: SessionUserIndexItem) => void;
}) {
  const errorMessage = error instanceof Error ? error.message : null;

  return (
    <aside className="flex min-h-0 flex-col border-b bg-muted/40 lg:border-b-0 lg:border-r">
      <div className="flex items-center justify-between gap-3 px-3 py-2">
        <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">User messages</span>
        <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-muted-foreground">
          {loading ? "..." : formatNumber(items.length)}
        </span>
      </div>
      <div className="max-h-44 min-h-0 overflow-auto border-t lg:max-h-none lg:flex-1">
        {loading ? (
          <div className="flex items-center px-3 py-4 text-xs text-muted-foreground">
            <Loader2 className="mr-2 animate-spin" size={14} />
            Loading index
          </div>
        ) : errorMessage ? (
          <div className="px-3 py-4 text-xs text-destructive">{errorMessage}</div>
        ) : items.length ? (
          items.map((item) => {
            const active = item.line_no === activeLineNo || item.event_index === pendingEventIndex;
            const timeLabel = item.timestamp ? formatTime(Date.parse(item.timestamp) / 1000) : "";
            return (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "block w-full border-b px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-white",
                  active ? "bg-blue-50" : "bg-transparent",
                )}
                onClick={() => onJump(item)}
              >
                <span className="line-clamp-2 break-words text-sm font-semibold leading-5 text-foreground">
                  {userIndexLabel(item)}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                  {timeLabel ? <span>{timeLabel}</span> : null}
                  <span>line {item.line_no}</span>
                  <span>{formatBytes(item.body_bytes)}</span>
                </span>
              </button>
            );
          })
        ) : (
          <div className="px-3 py-4 text-xs text-muted-foreground">No user messages</div>
        )}
      </div>
    </aside>
  );
}

export function SessionEventList({
  activeId,
  detailPending,
  totalEventCount,
}: {
  activeId: string | null;
  detailPending: boolean;
  totalEventCount: number | null;
}) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const [focusedLineNo, setFocusedLineNo] = useState<number | null>(null);
  const [pendingJumpIndex, setPendingJumpIndex] = useState<number | null>(null);
  const events = useInfiniteQuery({
    queryKey: ["session-events", activeId],
    queryFn: ({ pageParam }) =>
      api.sessionEvents(activeId!, { cursor: pageParam as string | null, limit: SESSION_EVENTS_PAGE_SIZE }),
    enabled: Boolean(activeId),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
  const userIndex = useQuery({
    queryKey: ["session-user-index", activeId],
    queryFn: () => api.sessionUserIndex(activeId!),
    enabled: Boolean(activeId),
    staleTime: Infinity,
  });
  const eventItems = useMemo(() => events.data?.pages.flatMap((page) => page.items) ?? [], [events.data]);
  const userIndexItems = userIndex.data?.items ?? [];
  const lastIndexedUser = userIndexItems[userIndexItems.length - 1];
  const knownRowCount = Math.max(totalEventCount ?? 0, eventItems.length, (lastIndexedUser?.event_index ?? -1) + 1);
  const rowCount = events.hasNextPage ? Math.max(knownRowCount, eventItems.length + 1) : Math.max(knownRowCount, eventItems.length);
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 176,
    overscan: 8,
  });
  const virtualItems = virtualizer.getVirtualItems();

  const jumpToUserMessage = useCallback(
    (item: SessionUserIndexItem) => {
      setFocusedLineNo(item.line_no);
      setPendingJumpIndex(item.event_index);
      virtualizer.scrollToIndex(Math.min(item.event_index, Math.max(rowCount - 1, 0)), { align: "start" });
    },
    [rowCount, virtualizer],
  );

  useEffect(() => {
    parentRef.current?.scrollTo({ top: 0 });
    virtualizer.scrollToOffset(0);
    setFocusedLineNo(null);
    setPendingJumpIndex(null);
  }, [activeId, virtualizer]);

  useEffect(() => {
    if (pendingJumpIndex === null) return;
    if (pendingJumpIndex < eventItems.length) {
      virtualizer.scrollToIndex(pendingJumpIndex, { align: "start" });
      setPendingJumpIndex(null);
      return;
    }
    if (events.hasNextPage && !events.isFetchingNextPage) {
      events.fetchNextPage();
    }
  }, [eventItems.length, events, pendingJumpIndex, virtualizer]);

  useEffect(() => {
    const lastItem = virtualItems[virtualItems.length - 1];
    if (!lastItem || !events.hasNextPage || events.isFetchingNextPage) return;
    if (lastItem.index >= eventItems.length - 12) {
      events.fetchNextPage();
    }
  }, [eventItems.length, events, virtualItems]);

  if (detailPending && activeId) {
    return (
      <div className="flex h-40 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 animate-spin" size={18} />
        Loading
      </div>
    );
  }

  if (!activeId) {
    return <div className="p-4 text-sm text-muted-foreground">No session selected</div>;
  }

  if (events.isPending) {
    return (
      <div className="flex h-40 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 animate-spin" size={18} />
        Loading
      </div>
    );
  }

  if (events.error) {
    return <div className="p-4 text-sm text-destructive">{events.error.message}</div>;
  }

  if (!eventItems.length) {
    return <div className="p-4 text-sm text-muted-foreground">No event content</div>;
  }

  return (
    <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] lg:grid-cols-[240px_minmax(0,1fr)] lg:grid-rows-1">
      <SessionUserDirectory
        items={userIndexItems}
        loading={userIndex.isPending}
        error={userIndex.error}
        activeLineNo={focusedLineNo}
        pendingEventIndex={pendingJumpIndex}
        onJump={jumpToUserMessage}
      />
      <div ref={parentRef} className="min-h-0 overflow-auto">
        <div className="sticky top-0 z-10 border-b bg-white px-4 py-2 text-xs font-semibold text-muted-foreground">
          Showing {formatNumber(eventItems.length)} of {formatNumber(totalEventCount ?? eventItems.length)} events
        </div>
        <div className="relative" style={{ height: `${virtualizer.getTotalSize()}px` }}>
          {virtualItems.map((virtualRow) => {
            const event = eventItems[virtualRow.index];
            return (
              <div
                key={event?.id ?? `placeholder-${virtualRow.index}`}
                ref={virtualizer.measureElement}
                data-index={virtualRow.index}
                className="absolute left-0 top-0 w-full"
                style={{ transform: `translateY(${virtualRow.start}px)` }}
              >
                {event ? (
                  <EventRow event={event} threadId={activeId} focused={event.line_no === focusedLineNo} />
                ) : (
                  <div className="flex items-center justify-center px-4 py-6 text-sm text-muted-foreground">
                    {events.isFetchingNextPage ? (
                      <>
                        <Loader2 className="mr-2 animate-spin" size={16} />
                        Loading more
                      </>
                    ) : (
                      "Scroll to load more"
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
