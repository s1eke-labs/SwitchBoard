import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { api, SessionEventPreview, SessionUserIndexItem } from "@/lib/api";
import { translate, useI18n } from "@/i18n";
import { formatAppError } from "@/lib/errors";
import { cn, formatNumber, formatTime } from "@/lib/utils";
import { Badge } from "@/components/heroui/badge";
import { Button } from "@/components/heroui/button";
import { formatBytes, fullEventBody, userIndexLabel } from "@/features/sessions/sessionUtils";

const SESSION_EVENTS_PAGE_SIZE = 80;

type SessionEventDisplayRole = "user" | "assistant" | "system";

const eventDisplayStyles: Record<
  SessionEventDisplayRole,
  {
    avatar: string;
    badgeTone: "blue" | "green" | "neutral";
    avatarClassName: string;
    panelClassName: string;
  }
> = {
  user: {
    avatar: "U",
    badgeTone: "blue",
    avatarClassName: "bg-blue-600 text-white shadow-blue-100",
    panelClassName: "border-blue-200 bg-blue-50/70",
  },
  assistant: {
    avatar: "A",
    badgeTone: "green",
    avatarClassName: "bg-emerald-600 text-white shadow-emerald-100",
    panelClassName: "border-emerald-200 bg-emerald-50/65",
  },
  system: {
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

function eventDisplayLabel(role: SessionEventDisplayRole) {
  if (role === "user") return translate("sessions.user");
  if (role === "assistant") return translate("sessions.assistant");
  return translate("sessions.system");
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
      <div className="relative px-5 py-0.5 sm:px-6">
        <button
          type="button"
          className={cn(
            "grid min-h-7 w-full grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-2.5 rounded-md text-left text-[11px] transition-colors",
            canExpand ? "cursor-pointer hover:bg-muted/50" : "cursor-default",
            expanded ? "bg-muted/50" : "bg-transparent",
            focused ? "ring-2 ring-ring" : "",
          )}
          onClick={() => {
            if (canExpand) setExpanded((value) => !value);
          }}
          aria-expanded={canExpand ? expanded : undefined}
        >
          <span className="relative z-10 flex h-8 w-8 items-center justify-center bg-white text-foreground">
            {canExpand ? expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} /> : null}
          </span>
          <span className="min-w-0 truncate text-[10px] font-semibold text-foreground">{title}</span>
          <span className="shrink-0 text-[11px] text-muted-foreground">{timeLabel}</span>
        </button>
        {expanded ? (
          <div className="ml-10 mt-1 rounded-lg border bg-white px-3.5 py-2 shadow-soft">
            <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span>{translate("sessions.line", { line: event.line_no })}</span>
              {event.body_bytes > 0 ? <span>{sizeLabel}</span> : null}
            </div>
            {body ? <pre className="whitespace-pre-wrap break-words text-xs leading-5 text-foreground">{body}</pre> : null}
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {event.body_truncated && fullEvent.isFetching ? (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="animate-spin" size={12} />
                  {translate("common.loading")}
                </span>
              ) : null}
              {fullEvent.error ? <span className="text-xs text-destructive">{formatAppError(fullEvent.error)}</span> : null}
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="relative px-4 py-2.5 sm:px-5">
      <div className="flex w-full items-start gap-3">
        <div
          className={cn(
            "relative z-10 mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold shadow-sm",
            display.avatarClassName,
          )}
          aria-hidden="true"
        >
          {display.avatar}
        </div>
        <article
          className={cn(
            "min-w-0 flex-1 rounded-lg border px-3.5 py-3 transition-shadow",
            display.panelClassName,
            focused ? "ring-2 ring-ring" : "",
          )}
        >
          <div className="mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Badge tone={display.badgeTone}>{eventDisplayLabel(displayRole)}</Badge>
              <span className="text-xs font-medium text-muted-foreground">{translate("sessions.line", { line: event.line_no })}</span>
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
                {expanded
                  ? translate("sessions.collapseWithSize", { size: sizeLabel })
                  : translate("sessions.loadFullWithSize", { size: sizeLabel })}
              </Button>
              {fullEvent.isFetching ? (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="animate-spin" size={12} />
                  {translate("common.loading")}
                </span>
              ) : null}
              {fullEvent.error ? <span className="text-xs text-destructive">{formatAppError(fullEvent.error)}</span> : null}
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
  const errorMessage = error ? formatAppError(error) : null;

  return (
    <aside className="flex min-h-0 flex-col border-b bg-white lg:border-b-0 lg:border-r">
      <div className="flex h-11 items-center justify-between gap-3 border-b px-4">
        <span className="text-xs font-bold uppercase text-muted-foreground">{translate("sessions.userMessages")}</span>
        <span className="rounded-full border bg-white px-2 py-0.5 text-xs font-semibold text-foreground">
          {loading ? "..." : formatNumber(items.length)}
        </span>
      </div>
      <div className="max-h-52 min-h-0 overflow-auto px-3 py-4 lg:max-h-none lg:flex-1">
        {loading ? (
          <div className="flex items-center px-1 py-4 text-xs text-muted-foreground">
            <Loader2 className="mr-2 animate-spin" size={14} />
            {translate("sessions.loadingIndex")}
          </div>
        ) : errorMessage ? (
          <div className="px-1 py-4 text-xs text-destructive">{errorMessage}</div>
        ) : items.length ? (
          <div className="space-y-3">
            {items.map((item) => {
              const active = item.line_no === activeLineNo || item.event_index === pendingEventIndex;
              const timeLabel = item.timestamp ? formatTime(Date.parse(item.timestamp) / 1000) : "";
              return (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    "flex w-full items-start gap-3 rounded-lg border bg-white px-3.5 py-3 text-left transition-colors hover:bg-muted/40",
                    active ? "border-blue-200 bg-blue-50/80 ring-1 ring-blue-100" : "border-border",
                  )}
                  onClick={() => onJump(item)}
                >
                  <span
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white"
                    aria-hidden="true"
                  >
                    U
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 break-words text-sm font-semibold leading-5 text-foreground">
                      {userIndexLabel(item)}
                    </span>
                    <span className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
                      {timeLabel ? <span>{timeLabel}</span> : null}
                      {timeLabel ? <span aria-hidden="true">·</span> : null}
                      <span>{translate("sessions.line", { line: item.line_no })}</span>
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="px-1 py-4 text-xs text-muted-foreground">{translate("sessions.noUserMessages")}</div>
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
  useI18n();
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
        {translate("common.loading")}
      </div>
    );
  }

  if (!activeId) {
    return <div className="p-4 text-sm text-muted-foreground">{translate("sessions.noSessionSelected")}</div>;
  }

  if (events.isPending) {
    return (
      <div className="flex h-40 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 animate-spin" size={18} />
        {translate("common.loading")}
      </div>
    );
  }

  if (events.error) {
    return <div className="p-4 text-sm text-destructive">{formatAppError(events.error)}</div>;
  }

  if (!eventItems.length) {
    return <div className="p-4 text-sm text-muted-foreground">{translate("sessions.noEventContent")}</div>;
  }

  return (
    <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] lg:grid-cols-[320px_minmax(0,1fr)] lg:grid-rows-1">
      <SessionUserDirectory
        items={userIndexItems}
        loading={userIndex.isPending}
        error={userIndex.error}
        activeLineNo={focusedLineNo}
        pendingEventIndex={pendingJumpIndex}
        onJump={jumpToUserMessage}
      />
      <section className="flex min-h-0 flex-col bg-white">
        <div className="flex h-11 shrink-0 items-center justify-between gap-3 border-b px-5">
          <span className="text-xs font-bold uppercase text-muted-foreground">{translate("sessions.eventsTimeline")}</span>
          <span className="text-xs text-muted-foreground">
            {translate("sessions.showingEvents", {
              shown: formatNumber(eventItems.length),
              total: formatNumber(totalEventCount ?? eventItems.length),
            })}
          </span>
        </div>
        <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
          <div className="relative" style={{ height: `${virtualizer.getTotalSize()}px` }}>
            <div className="pointer-events-none absolute bottom-0 left-[34px] top-0 border-l border-dashed border-border" />
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
                          {translate("sessions.loadMore")}
                        </>
                      ) : (
                        translate("sessions.scrollToLoadMore")
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}
