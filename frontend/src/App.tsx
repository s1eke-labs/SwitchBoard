import { FormEvent, ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  BarChart3,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock,
  Eye,
  LayoutGrid,
  Loader2,
  LogIn,
  LogOut,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { api, AccountDTO, LimitDTO, ScanResult, SessionEvent, SessionEventPreview, SessionSummary, UsageAggregatePointDTO } from "@/lib/api";
import { cn, formatChartTime, formatNumber, formatPercent, formatTime, shortId } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type RangeKey = "24h" | "7d" | "30d" | "90d";

type ChartPoint = UsageAggregatePointDTO & {
  label: string;
};

type AccountDensity = "large" | "medium" | "small";

const accountDensityOrder: AccountDensity[] = ["large", "medium", "small"];
const accountDensityLabels: Record<AccountDensity, string> = {
  large: "large",
  medium: "medium",
  small: "small",
};
const accountGridClasses: Record<AccountDensity, string> = {
  large: "grid-cols-2",
  medium: "grid-cols-3",
  small: "grid-cols-4",
};
const collapsedRowsByDensity: Record<AccountDensity, number> = {
  large: 1,
  medium: 1,
  small: 2,
};

type AppRoute =
  | { page: "dashboard" }
  | { page: "sessions"; threadId: string | null };

const ranges: Record<RangeKey, { label: string }> = {
  "24h": { label: "24h" },
  "7d": { label: "7d" },
  "30d": { label: "30d" },
  "90d": { label: "90d" },
};
const SESSIONS_PAGE_SIZE = 7;
const SESSION_EVENTS_PAGE_SIZE = 80;
const usageSeries = [
  {
    key: "input_tokens",
    label: "Input",
    stroke: "#0075de",
    fill: "url(#usage-input)",
    legendColor: "#0075de",
  },
  {
    key: "cache_hit_tokens",
    label: "Cache hit",
    stroke: "#2a9d99",
    fill: "url(#usage-cache)",
    legendColor: "#2a9d99",
  },
  {
    key: "output_tokens",
    label: "Output",
    stroke: "#dd5b00",
    fill: "transparent",
    legendColor: "#dd5b00",
  },
] as const;

function formatThousandsAxis(value: number) {
  if (!Number.isFinite(value) || value === 0) return "0";
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: Math.abs(value) < 10000 ? 1 : 0 }).format(value / 1000)}k`;
}

function errorStatus(error: unknown) {
  return typeof error === "object" && error !== null && "status" in error
    ? Number((error as { status: number }).status)
    : 0;
}

function parseRoute(pathname = window.location.pathname): AppRoute {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] === "sessions") {
    const rawThreadId = segments.slice(1).join("/");
    return { page: "sessions", threadId: rawThreadId ? decodeURIComponent(rawThreadId) : null };
  }
  return { page: "dashboard" };
}

function sessionPath(threadId: string) {
  return `/sessions/${encodeURIComponent(threadId)}`;
}

function useRoute() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute());

  useEffect(() => {
    function handlePopState() {
      setRoute(parseRoute());
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback((path: string, replace = false) => {
    if (path === `${window.location.pathname}${window.location.search}${window.location.hash}`) return;
    if (replace) {
      window.history.replaceState(null, "", path);
    } else {
      window.history.pushState(null, "", path);
    }
    setRoute(parseRoute());
  }, []);

  return { route, navigate };
}

function useElementSize<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const ref = useCallback((element: T | null) => {
    setNode(element);
  }, []);

  useEffect(() => {
    if (!node) return;
    const target = node;

    function updateSize(entry?: ResizeObserverEntry) {
      const rect = entry?.contentRect ?? target.getBoundingClientRect();
      const width = Math.floor(rect.width);
      const height = Math.floor(rect.height);
      setSize((current) => (current.width === width && current.height === height ? current : { width, height }));
    }

    updateSize();
    const observer = new ResizeObserver((entries) => updateSize(entries[0]));
    observer.observe(target);
    return () => observer.disconnect();
  }, [node]);

  return { ref, ...size };
}

function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(password),
    onSuccess: onDone,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate();
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border bg-white p-5 shadow-soft">
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Activity size={20} />
          </div>
          <div>
            <h1 className="text-xl font-bold">SwitchBoard</h1>
            <p className="text-sm text-muted-foreground">Codex console</p>
          </div>
        </div>
        <Input
          autoFocus
          type="password"
          placeholder="Password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {login.error ? <p className="mt-3 text-sm text-destructive">{login.error.message}</p> : null}
        <Button className="mt-4 w-full" disabled={!password || login.isPending}>
          {login.isPending ? <Loader2 className="animate-spin" size={16} /> : <Eye size={16} />}
          Sign in
        </Button>
      </form>
    </main>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" role="presentation" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="switch-modal-title"
        className="w-full max-w-md rounded-lg border bg-white p-5 shadow-soft"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="switch-modal-title" className="text-lg font-bold">
            {title}
          </h2>
          <Button variant="ghost" size="icon" aria-label="Close modal" title="Close modal" onClick={onClose}>
            <X size={16} />
          </Button>
        </div>
        <div className="mt-3 text-sm leading-6 text-muted-foreground">{children}</div>
      </div>
    </div>
  );
}

function LimitMeter({ label, limit }: { label: string; limit: LimitDTO | null }) {
  const remaining = limit?.remaining_percent ?? 100;
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold text-muted-foreground">{label}</span>
        <span className="font-bold">{formatPercent(remaining)}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full limit-bar" style={{ width: `${Math.max(0, Math.min(100, remaining))}%` }} />
      </div>
      <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
        <Clock size={12} />
        <span>{formatTime(limit?.resets_at)}</span>
      </div>
    </div>
  );
}

function LimitSummary({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md bg-muted px-2.5 py-2">
      <div className="truncate text-xs font-semibold text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-base font-bold leading-none">{value}</div>
    </div>
  );
}

function AccountCard({
  account,
  onHide,
  onRename,
  onSwitch,
  renaming,
  switching,
  density,
  expanded,
}: {
  account: AccountDTO;
  onHide: (id: string) => void;
  onRename: (id: string, customName: string | null) => Promise<unknown>;
  onSwitch: (id: string) => void;
  renaming: boolean;
  switching: boolean;
  density: AccountDensity;
  expanded: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftName, setDraftName] = useState(account.custom_name ?? account.display_name);
  const [renameError, setRenameError] = useState<string | null>(null);

  function beginEditing() {
    setDraftName(account.custom_name ?? account.display_name);
    setRenameError(null);
    setIsEditing(true);
  }

  function cancelEditing() {
    setIsEditing(false);
    setRenameError(null);
  }

  async function saveName(event: FormEvent) {
    event.preventDefault();
    setRenameError(null);
    try {
      await onRename(account.account_id, draftName.trim() || null);
      setIsEditing(false);
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : "Rename failed");
    }
  }

  const isLarge = density === "large";
  const isMedium = density === "medium";
  const isSmall = density === "small";
  const fiveHour = formatPercent(account.five_hour?.remaining_percent ?? 100);
  const weekly = formatPercent(account.weekly?.remaining_percent ?? 100);
  const showUserName = Boolean(account.user_name && account.user_name !== account.display_name);
  const actionButtonClass = isLarge ? undefined : "h-8 w-8";
  const iconSize = isLarge ? 16 : 15;

  return (
    <Card className={cn("h-full min-h-0 overflow-hidden", account.current && "border-blue-300 bg-blue-50/40")}>
      <CardContent
        className={cn(
          "flex h-full min-h-0 flex-col",
          isLarge ? (expanded ? "p-5" : "p-4") : isMedium ? (expanded ? "p-4" : "p-3.5") : expanded ? "p-3.5" : "p-3",
        )}
      >
        <div className={cn("flex items-start justify-between gap-3", isLarge ? (expanded ? "mb-5" : "mb-4") : isMedium ? "mb-3" : "mb-2.5")}>
          <div className="min-w-0 flex-1">
            {isEditing ? (
              <form onSubmit={saveName} className="flex min-w-0 flex-wrap items-center gap-2">
                <Input
                  autoFocus
                  className={isSmall ? "h-8 w-32 max-w-full" : isMedium ? "h-8 w-44 max-w-full" : "h-9 w-56 max-w-full"}
                  placeholder="Custom name"
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                />
                <Button
                  aria-label="Save name"
                  title="Save name"
                  size="icon"
                  className={actionButtonClass}
                  type="submit"
                  disabled={renaming}
                >
                  {renaming ? <Loader2 className="animate-spin" size={iconSize} /> : <Check size={iconSize} />}
                </Button>
                <Button
                  aria-label="Cancel rename"
                  title="Cancel rename"
                  size="icon"
                  className={actionButtonClass}
                  type="button"
                  variant="ghost"
                  onClick={cancelEditing}
                  disabled={renaming}
                >
                  <X size={iconSize} />
                </Button>
              </form>
            ) : (
              <div className={cn("flex min-w-0 flex-wrap items-center gap-2", isSmall && "gap-x-1.5 gap-y-1")}>
                <h3 className={cn("min-w-0 truncate font-bold", isSmall ? "text-sm" : "text-base")}>{account.display_name}</h3>
                {account.current ? <Badge tone="blue">Current</Badge> : null}
                {account.expired ? <Badge tone="orange">Expired</Badge> : null}
                {!isSmall && showUserName ? <Badge tone="neutral">{account.user_name}</Badge> : null}
                {!isSmall && account.plan_type ? <Badge tone="neutral">{account.plan_type}</Badge> : null}
              </div>
            )}
            {!isSmall ? <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{shortId(account.account_id)}</p> : null}
            {renameError ? <p className="mt-2 text-xs text-destructive">{renameError}</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {!account.current ? (
              <Button
                aria-label="Switch account"
                title="Switch account"
                size="icon"
                variant="secondary"
                className={actionButtonClass}
                onClick={() => onSwitch(account.account_id)}
                disabled={switching}
              >
                {switching ? <Loader2 className="animate-spin" size={iconSize} /> : <LogIn size={iconSize} />}
              </Button>
            ) : null}
            {!isEditing ? (
              <Button
                aria-label="Rename account"
                title="Rename account"
                size="icon"
                variant="ghost"
                className={actionButtonClass}
                onClick={beginEditing}
              >
                <Pencil size={iconSize} />
              </Button>
            ) : null}
            {!account.current ? (
              <Button
                aria-label="Hide account"
                title="Hide account"
                size="icon"
                variant="ghost"
                className={actionButtonClass}
                onClick={() => onHide(account.account_id)}
                disabled={switching}
              >
                <Trash2 size={iconSize} />
              </Button>
            ) : null}
          </div>
        </div>
        {isSmall ? (
          <div className="mt-auto grid grid-cols-2 gap-2">
            <LimitSummary label="5h" value={fiveHour} />
            <LimitSummary label="Weekly" value={weekly} />
          </div>
        ) : (
          <div className={`grid ${isLarge ? "gap-4 sm:grid-cols-2" : "gap-3"}`}>
            <LimitMeter label="5h remaining" limit={account.five_hour} />
            <LimitMeter label="Weekly remaining" limit={account.weekly} />
          </div>
        )}
        {isLarge ? (
          <div className="mt-4 flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="truncate">Scanned {formatTime(account.last_scanned_at)}</span>
            {account.last_error ? (
              <span className="truncate text-orange-700">
                Last scan failed{account.failed_scan_count ? ` x${account.failed_scan_count}` : ""}
              </span>
            ) : null}
          </div>
        ) : account.last_error ? (
          <div className="mt-2 truncate text-xs text-orange-700">
            Last scan failed{account.failed_scan_count ? ` x${account.failed_scan_count}` : ""}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function AccountsPanel({ accounts }: { accounts: AccountDTO[] }) {
  const [expanded, setExpanded] = useState(false);
  const [density, setDensity] = useState<AccountDensity>("large");
  const [collapsedHeight, setCollapsedHeight] = useState(0);
  const [hasOverflowRow, setHasOverflowRow] = useState(false);
  const [switchNotice, setSwitchNotice] = useState<ScanResult | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const scan = useMutation({
    mutationFn: api.scan,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const switchAccount = useMutation({
    mutationFn: api.switchAccount,
    onSuccess: (result) => setSwitchNotice(result),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const hide = useMutation({
    mutationFn: api.hideAccount,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const rename = useMutation({
    mutationFn: ({ accountId, customName }: { accountId: string; customName: string | null }) =>
      api.renameAccount(accountId, customName),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const current = accounts.find((account) => account.current);
  const nextDensity = accountDensityOrder[(accountDensityOrder.indexOf(density) + 1) % accountDensityOrder.length];
  const densitySwitchLabel = `Accounts view: ${accountDensityLabels[density]}. Switch to ${accountDensityLabels[nextDensity]}`;
  const gridClass = accountGridClasses[density];
  const gridGapClass = expanded ? "gap-4" : density === "small" ? "gap-3" : "gap-4";
  const listStyle = expanded || collapsedHeight === 0 ? undefined : { maxHeight: `${collapsedHeight}px` };

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const target = grid;

    function measure() {
      const items = Array.from(target.children).filter((child): child is HTMLElement => child instanceof HTMLElement);
      if (!items.length) {
        setCollapsedHeight(0);
        setHasOverflowRow(false);
        return;
      }

      const rows: HTMLElement[][] = [];
      for (const item of items) {
        const row = rows.find((candidate) => Math.abs(candidate[0].offsetTop - item.offsetTop) < 4);
        if (row) {
          row.push(item);
        } else {
          rows.push([item]);
        }
      }

      const visibleRowCount = collapsedRowsByDensity[density];
      const visibleRows = rows.slice(0, visibleRowCount).flat();
      const firstTop = rows[0][0].offsetTop;
      const visibleBottom = Math.max(...visibleRows.map((item) => item.offsetTop + item.offsetHeight));
      setCollapsedHeight(Math.ceil(visibleBottom - firstTop));
      setHasOverflowRow(rows.length > visibleRowCount);
    }

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(target);
    for (const child of Array.from(target.children)) {
      if (child instanceof HTMLElement) observer.observe(child);
    }
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [accounts, density]);

  useEffect(() => {
    if (!hasOverflowRow) setExpanded(false);
  }, [hasOverflowRow]);

  return (
    <section className="h-full min-h-0">
      <div
        className={cn(
          "z-20 flex min-h-0 flex-col overflow-hidden rounded-lg bg-background",
          expanded ? "absolute inset-x-4 bottom-4 top-4 p-5 shadow-soft ring-1 ring-border" : "relative h-full",
        )}
      >
        <div className={cn("flex min-h-0 flex-1 flex-col", expanded ? "gap-5" : "gap-3")}>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-2xl font-bold">Accounts</h2>
              <p className="truncate text-sm text-muted-foreground">{current?.display_name ?? "No current account"}</p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {hasOverflowRow ? (
                <Button
                  aria-label={expanded ? "Collapse accounts" : "Expand accounts"}
                  title={expanded ? "Collapse accounts" : "Expand accounts"}
                  size="icon"
                  variant="secondary"
                  onClick={() => setExpanded((value) => !value)}
                >
                  {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </Button>
              ) : null}
              <Button
                aria-label={densitySwitchLabel}
                title={densitySwitchLabel}
                size="icon"
                variant="secondary"
                onClick={() => setDensity(nextDensity)}
              >
                <LayoutGrid size={16} />
              </Button>
              <Button onClick={() => scan.mutate()} disabled={scan.isPending}>
                {scan.isPending ? <Loader2 className="animate-spin" size={16} /> : <RefreshCw size={16} />}
                Scan
              </Button>
            </div>
          </div>
          {scan.data?.error ? (
            <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-800">{scan.data.error}</div>
          ) : null}
          {switchAccount.error ? (
            <div className="rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-800">{switchAccount.error.message}</div>
          ) : null}
          <div className={cn("min-h-0 flex-1", expanded ? "overflow-y-auto pr-2" : "overflow-hidden")} style={listStyle}>
            <div ref={gridRef} className={cn("grid", gridClass, gridGapClass)}>
              {accounts.map((account) => (
                <AccountCard
                  key={account.account_id}
                  account={account}
                  density={density}
                  expanded={expanded}
                  onHide={(id) => hide.mutate(id)}
                  onRename={(id, customName) => rename.mutateAsync({ accountId: id, customName })}
                  onSwitch={(id) => switchAccount.mutate(id)}
                  renaming={rename.isPending && rename.variables?.accountId === account.account_id}
                  switching={switchAccount.isPending && switchAccount.variables === account.account_id}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
      {switchNotice ? (
        <Modal title="Account switched" onClose={() => setSwitchNotice(null)}>
          <p>Switched to {switchNotice.account.display_name}. Restart Codex for the change to take effect.</p>
          {switchNotice.error ? (
            <p className="mt-3 rounded-md border border-orange-200 bg-orange-50 px-3 py-2 text-orange-800">
              Scan warning: {switchNotice.error}
            </p>
          ) : null}
        </Modal>
      ) : null}
    </section>
  );
}

function TrendsPanel() {
  const [range, setRange] = useState<RangeKey>("7d");
  const chartSize = useElementSize<HTMLDivElement>();
  const usageAggregates = useQuery({
    queryKey: ["usage-aggregates"],
    queryFn: api.usageAggregates,
    refetchInterval: 10 * 60 * 1000,
  });
  const selectedRange = usageAggregates.data?.ranges[range];

  const data = useMemo<ChartPoint[]>(
    () =>
      (selectedRange?.items ?? []).map((point) => ({
        ...point,
        label: formatChartTime(point.bucket_start, selectedRange?.bucket ?? "day"),
      })),
    [selectedRange],
  );
  const hasUsage = Boolean(selectedRange?.event_count);
  const chartReady = chartSize.width > 0 && chartSize.height > 0;

  return (
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <BarChart3 size={20} />
          <h2 className="text-2xl font-bold">Usage</h2>
        </div>
        <div className="inline-flex rounded-md border bg-white p-1">
          {(Object.keys(ranges) as RangeKey[]).map((key) => (
            <button
              key={key}
              onClick={() => setRange(key)}
              className={`h-8 min-w-12 rounded-sm px-3 text-sm font-semibold ${range === key ? "bg-foreground text-white" : "text-muted-foreground hover:bg-muted"}`}
            >
              {ranges[key].label}
            </button>
          ))}
        </div>
      </div>
      <Card className="min-h-0 flex-1 overflow-hidden">
        <CardContent className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          {usageAggregates.isPending ? (
            <div className="flex min-h-0 flex-1 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 animate-spin" size={18} />
              Loading
            </div>
          ) : hasUsage ? (
            <>
              <div ref={chartSize.ref} className="min-h-0 min-w-0 flex-1 overflow-hidden">
                {chartReady ? (
                  <AreaChart
                    width={chartSize.width}
                    height={chartSize.height}
                    data={data}
                    margin={{ left: 0, right: 12, top: 12, bottom: 28 }}
                  >
                    <defs>
                      <linearGradient id="usage-input" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#0075de" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#0075de" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="usage-cache" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2a9d99" stopOpacity={0.32} />
                        <stop offset="95%" stopColor="#2a9d99" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e7e2dc" />
                    <XAxis dataKey="label" tick={{ fontSize: 12 }} minTickGap={32} />
                    <YAxis
                      tick={{ fontSize: 12 }}
                      tickFormatter={(value) => formatThousandsAxis(Number(value))}
                      tickMargin={8}
                      width={88}
                    />
                    <Tooltip formatter={(value) => formatNumber(Number(value ?? 0))} />
                    {usageSeries.map((series) => (
                      <Area
                        key={series.key}
                        type="monotone"
                        dataKey={series.key}
                        name={series.label}
                        stroke={series.stroke}
                        fill={series.fill}
                        strokeWidth={2}
                      />
                    ))}
                  </AreaChart>
                ) : null}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-3">
                {usageSeries.map((series) => (
                  <div key={series.key} className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
                    <span className="h-0.5 w-6 rounded-full" style={{ backgroundColor: series.legendColor }} />
                    <span>{series.label}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground">No usage in range</div>
          )}
        </CardContent>
      </Card>
      <div className="grid shrink-0 gap-3 sm:grid-cols-4">
        <Metric label="Input" value={sum(data, "input_tokens")} />
        <Metric label="Cache created" value={sum(data, "cache_creation_tokens")} />
        <Metric label="Cache hit" value={sum(data, "cache_hit_tokens")} />
        <Metric label="Output" value={sum(data, "output_tokens")} />
      </div>
    </section>
  );
}

function sum<T extends Record<string, unknown>>(items: T[], key: keyof T) {
  return items.reduce((total, item) => total + Number(item[key] ?? 0), 0);
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-white p-3">
      <div className="text-xs font-semibold text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-bold">{formatNumber(value)}</div>
    </div>
  );
}

function fullEventBody(event: SessionEvent) {
  if (event.text !== undefined && event.text !== null) return event.text;
  if (event.arguments !== undefined && event.arguments !== null) return JSON.stringify(event.arguments, null, 2);
  if (event.data !== undefined && event.data !== null) return JSON.stringify(event.data, null, 2);
  return "";
}

function EventRow({ event, threadId }: { event: SessionEventPreview; threadId: string }) {
  const [expanded, setExpanded] = useState(false);
  const title = event.name ?? event.title ?? event.kind;
  const fullEvent = useQuery({
    queryKey: ["session-event", threadId, event.line_no],
    queryFn: () => api.sessionEvent(threadId, event.line_no),
    enabled: expanded && event.body_truncated,
    staleTime: Infinity,
  });
  const body = expanded && fullEvent.data ? fullEventBody(fullEvent.data) : event.body_preview;
  const canExpand = event.body_truncated;

  return (
    <div className="border-b px-4 py-3 last:border-b-0">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge tone={event.kind === "user" ? "blue" : event.kind === "assistant" ? "green" : "neutral"}>{title}</Badge>
          <span className="text-xs font-semibold text-muted-foreground">line {event.line_no}</span>
          {canExpand ? <span className="text-xs text-muted-foreground">{formatNumber(event.body_bytes)} bytes</span> : null}
        </div>
        <span className="text-xs text-muted-foreground">{event.timestamp ? formatTime(Date.parse(event.timestamp) / 1000) : ""}</span>
      </div>
      {body ? <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-foreground">{body}</pre> : null}
      {canExpand ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={() => setExpanded((value) => !value)}>
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {expanded ? "Collapse" : "Load full"}
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
    </div>
  );
}

function SessionEventList({
  activeId,
  detailPending,
  totalEventCount,
}: {
  activeId: string | null;
  detailPending: boolean;
  totalEventCount: number | null;
}) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const events = useInfiniteQuery({
    queryKey: ["session-events", activeId],
    queryFn: ({ pageParam }) =>
      api.sessionEvents(activeId!, { cursor: pageParam as string | null, limit: SESSION_EVENTS_PAGE_SIZE }),
    enabled: Boolean(activeId),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });
  const eventItems = useMemo(() => events.data?.pages.flatMap((page) => page.items) ?? [], [events.data]);
  const rowCount = eventItems.length + (events.hasNextPage ? 1 : 0);
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 176,
    overscan: 8,
  });
  const virtualItems = virtualizer.getVirtualItems();

  useEffect(() => {
    parentRef.current?.scrollTo({ top: 0 });
    virtualizer.scrollToOffset(0);
  }, [activeId, virtualizer]);

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
    <div ref={parentRef} className="min-h-0 flex-1 overflow-auto">
      <div className="sticky top-0 z-10 border-b bg-white px-4 py-2 text-xs font-semibold text-muted-foreground">
        Showing {formatNumber(eventItems.length)} of {formatNumber(totalEventCount ?? eventItems.length)} events
      </div>
      <div className="relative" style={{ height: `${virtualizer.getTotalSize()}px` }}>
        {virtualItems.map((virtualRow) => {
          const event = eventItems[virtualRow.index];
          return (
            <div
              key={event?.id ?? "loader"}
              ref={virtualizer.measureElement}
              data-index={virtualRow.index}
              className="absolute left-0 top-0 w-full"
              style={{ transform: `translateY(${virtualRow.start}px)` }}
            >
              {event ? (
                <EventRow event={event} threadId={activeId} />
              ) : (
                <div className="flex items-center justify-center border-b px-4 py-6 text-sm text-muted-foreground">
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
  );
}

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

function SessionsPage({
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

function AppShell({
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

function Dashboard({ accounts }: { accounts: AccountDTO[] }) {
  return (
    <div className="relative mx-auto grid min-h-0 w-full max-w-7xl flex-1 grid-rows-[minmax(0,38fr)_minmax(0,62fr)] gap-4 overflow-hidden px-4 py-4">
      <AccountsPanel accounts={accounts} />
      <div className="min-h-0 flex-1 overflow-hidden">
        <TrendsPanel />
      </div>
    </div>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const { route, navigate } = useRoute();
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: api.accounts,
  });

  if (accounts.error && errorStatus(accounts.error) === 401) {
    return <Login onDone={() => queryClient.invalidateQueries({ queryKey: ["accounts"] })} />;
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
        <Dashboard accounts={accounts.data ?? []} />
      )}
    </AppShell>
  );
}
