import { ReactNode, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, ChevronDown, ChevronLeft, ChevronRight, Database, DollarSign, Layers3, Loader2, ReceiptText, UserRound } from "lucide-react";
import { AccountDTO, api, UsageRequestLogDTO, UsageRequestLogsResponse } from "@/lib/api";
import { getCurrentLocale, translate, useI18n } from "@/i18n";
import { formatAppError } from "@/lib/errors";
import { cn, formatNumber, formatTime } from "@/lib/utils";
import { PageSelector } from "@/components/PageSelector";
import { Button } from "@/components/heroui/button";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { Badge } from "@/components/heroui/badge";

const REQUEST_LOG_PAGE_SIZE = 30;
const ALL_ACCOUNTS_FILTER = "__all__";
const UNASSIGNED_ACCOUNT_FILTER = "__unassigned__";

type RangeKey = "24h" | "7d" | "30d";
type AccountFilterValue = typeof ALL_ACCOUNTS_FILTER | typeof UNASSIGNED_ACCOUNT_FILTER | string;

const ranges: Record<RangeKey, { label: string; seconds: number }> = {
  "24h": { label: "24h", seconds: 60 * 60 * 24 },
  "7d": { label: "7d", seconds: 60 * 60 * 24 * 7 },
  "30d": { label: "30d", seconds: 60 * 60 * 24 * 30 },
};

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function formatUsd(value: number | null, known: boolean) {
  if (!known || value === null) return translate("common.unknown");
  return new Intl.NumberFormat(getCurrentLocale(), {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 1 ? 4 : 2,
    maximumFractionDigits: value < 1 ? 6 : 2,
  }).format(value);
}

function formatCompactThousands(value: number | null | undefined) {
  const safeValue = value ?? 0;
  if (Math.abs(safeValue) < 1000) return formatNumber(safeValue);
  return `${new Intl.NumberFormat(getCurrentLocale(), { maximumFractionDigits: 1 }).format(safeValue / 1000)}k`;
}

function RangeButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-8 min-w-12 rounded-sm px-3 text-sm font-semibold transition-colors",
        active ? "bg-foreground text-white" : "text-muted-foreground hover:bg-muted",
      )}
    >
      {label}
    </button>
  );
}

function AccountFilter({
  accounts,
  value,
  disabled,
  onChange,
}: {
  accounts: AccountDTO[];
  value: AccountFilterValue;
  disabled: boolean;
  onChange: (value: AccountFilterValue) => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const selectedAccount = accounts.find((account) => account.account_id === value);
  const label =
    value === ALL_ACCOUNTS_FILTER
      ? t("requestLogs.allAccounts")
      : value === UNASSIGNED_ACCOUNT_FILTER
        ? t("requestLogs.unassigned")
        : selectedAccount?.display_name ?? t("common.unknown");
  const options = [
    { value: ALL_ACCOUNTS_FILTER, label: t("requestLogs.allAccounts") },
    { value: UNASSIGNED_ACCOUNT_FILTER, label: t("requestLogs.unassigned") },
    ...accounts.map((account) => ({ value: account.account_id, label: account.display_name })),
  ];

  return (
    <div className="relative">
      <button
        type="button"
        className="inline-flex h-9 min-w-48 max-w-64 items-center justify-between gap-2 rounded-md border bg-white px-3 text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="inline-flex min-w-0 items-center gap-2">
          <UserRound size={15} className="shrink-0 text-muted-foreground" />
          <span className="truncate">{label}</span>
        </span>
        <ChevronDown size={15} className="shrink-0 text-muted-foreground" />
      </button>
      {open ? (
        <div className="absolute right-0 top-11 z-20 max-h-72 w-64 overflow-auto rounded-lg border bg-white p-2 shadow-soft">
          <div className="space-y-1" role="listbox" aria-label={t("requestLogs.accountFilter")}>
            {options.map((option) => {
              const active = option.value === value;
              return (
                <button
                  key={option.value}
                  type="button"
                  className={cn(
                    "flex h-8 w-full items-center rounded-md px-2 text-left text-sm font-semibold transition-colors hover:bg-muted",
                    active ? "bg-foreground text-white hover:bg-foreground" : "text-foreground",
                  )}
                  onClick={() => {
                    setOpen(false);
                    onChange(option.value);
                  }}
                  role="option"
                  aria-selected={active}
                >
                  <span className="truncate">{option.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SummaryCard({
  title,
  value,
  icon,
  iconClassName,
  children,
}: {
  title: string;
  value: string;
  icon: ReactNode;
  iconClassName: string;
  children?: ReactNode;
}) {
  return (
    <Card className="min-h-44 rounded-lg shadow-none">
      <CardContent className="flex h-full flex-col p-5">
        <div className="flex items-start justify-between gap-4">
          <h3 className="text-base font-bold text-muted-foreground">{title}</h3>
          <div className={cn("flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl", iconClassName)}>{icon}</div>
        </div>
        <div className="mt-7 text-3xl font-bold tabular-nums text-foreground">{value}</div>
        {children ? <div className="mt-5 border-t pt-4 text-sm text-muted-foreground">{children}</div> : null}
      </CardContent>
    </Card>
  );
}

function SummaryMetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span>{label}</span>
      <span className="font-medium tabular-nums text-foreground">{value}</span>
    </div>
  );
}

function RequestLogSummaryCards({ data }: { data: UsageRequestLogsResponse | undefined }) {
  const summary = data?.summary;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <SummaryCard
        title={translate("requestLogs.totalRequests")}
        value={formatNumber(summary?.request_count ?? 0)}
        icon={<Activity size={24} />}
        iconClassName="bg-blue-50 text-blue-600"
      />
      <SummaryCard
        title={translate("requestLogs.totalCost")}
        value={formatUsd(summary?.total_cost_usd ?? null, Boolean(summary?.cost_known))}
        icon={<DollarSign size={25} />}
        iconClassName="bg-emerald-50 text-emerald-600"
      />
      <SummaryCard
        title={translate("requestLogs.totalTokens")}
        value={formatNumber(summary?.total_tokens ?? 0)}
        icon={<Layers3 size={25} />}
        iconClassName="bg-purple-50 text-purple-600"
      >
        <div className="space-y-1.5">
          <SummaryMetricLine label={translate("usage.input")} value={formatCompactThousands(summary?.input_tokens)} />
          <SummaryMetricLine label={translate("usage.output")} value={formatCompactThousands(summary?.output_tokens)} />
        </div>
      </SummaryCard>
      <SummaryCard
        title={translate("requestLogs.cacheTokens")}
        value={formatNumber(summary?.cache_hit_tokens ?? 0)}
        icon={<Database size={25} />}
        iconClassName="bg-orange-50 text-orange-600"
      >
        <div className="space-y-1.5">
          <SummaryMetricLine label={translate("usage.cacheCreated")} value={formatCompactThousands(summary?.cache_creation_tokens)} />
          <SummaryMetricLine label={translate("usage.cacheHit")} value={formatCompactThousands(summary?.cache_hit_tokens)} />
        </div>
      </SummaryCard>
    </div>
  );
}

function RequestLogRow({ log }: { log: UsageRequestLogDTO }) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="whitespace-nowrap px-4 py-3 align-top text-sm font-medium text-foreground">
        {formatTime(log.occurred_at)}
      </td>
      <td className="px-4 py-3 align-top">
        <Badge className="max-w-full truncate" tone={log.account_id ? "blue" : "neutral"}>
          {log.account_display_name ?? translate("requestLogs.unassigned")}
        </Badge>
      </td>
      <td className="px-4 py-3 align-top">
        <Badge className="max-w-full truncate" tone="neutral">
          {log.billing_model ?? translate("common.unknown")}
        </Badge>
      </td>
      <td className="px-4 py-3 align-top text-right tabular-nums">
        <div className="font-semibold text-foreground">{formatNumber(log.input_tokens)}</div>
      </td>
      <td className="px-4 py-3 align-top text-right tabular-nums">
        <div className="font-semibold text-foreground">{formatNumber(log.cache_hit_tokens)}</div>
      </td>
      <td className="px-4 py-3 align-top text-right tabular-nums">
        <div className="font-semibold text-foreground">{formatNumber(log.output_tokens)}</div>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right align-top tabular-nums">
        <div className="font-semibold text-foreground">{formatUsd(log.total_cost_usd, log.cost_known)}</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {translate("requestLogs.tokensWithCount", { count: formatNumber(log.total_tokens) })}
        </div>
      </td>
    </tr>
  );
}

export function RequestLogsPage({ accounts }: { accounts: AccountDTO[] }) {
  const { t } = useI18n();
  const [range, setRange] = useState<RangeKey>("24h");
  const [accountFilter, setAccountFilter] = useState<AccountFilterValue>(ALL_ACCOUNTS_FILTER);
  const [windowEnd, setWindowEnd] = useState(() => nowSeconds());
  const [page, setPage] = useState(1);
  const windowBounds = useMemo(
    () => ({
      from: windowEnd - ranges[range].seconds,
      to: windowEnd,
    }),
    [range, windowEnd],
  );
  const requestLogs = useQuery({
    queryKey: ["usage-request-logs", range, windowEnd, accountFilter, page],
    queryFn: () =>
      api.usageRequestLogs({
        from: windowBounds.from,
        to: windowBounds.to,
        account_id: accountFilter === ALL_ACCOUNTS_FILTER ? undefined : accountFilter,
        page,
        limit: REQUEST_LOG_PAGE_SIZE,
      }),
    placeholderData: (previousData) => previousData,
  });
  const logs = requestLogs.data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((requestLogs.data?.total_count ?? 0) / REQUEST_LOG_PAGE_SIZE));

  function selectRange(nextRange: RangeKey) {
    setRange(nextRange);
    setWindowEnd(nowSeconds());
    setPage(1);
  }

  function selectPage(targetPage: number) {
    if (targetPage === page || targetPage < 1 || targetPage > totalPages || requestLogs.isFetching) return;
    setPage(targetPage);
  }

  function selectAccountFilter(value: AccountFilterValue) {
    setAccountFilter(value);
    setPage(1);
  }

  return (
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="flex items-center gap-2">
          <ReceiptText size={20} strokeWidth={1.8} />
          <h2 className="text-2xl font-bold leading-tight">{t("requestLogs.title")}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AccountFilter accounts={accounts} value={accountFilter} disabled={requestLogs.isFetching} onChange={selectAccountFilter} />
          <div className="inline-flex rounded-md border bg-white p-1">
            {(Object.keys(ranges) as RangeKey[]).map((key) => (
              <RangeButton key={key} active={range === key} label={ranges[key].label} onClick={() => selectRange(key)} />
            ))}
          </div>
        </div>
      </div>
      <RequestLogSummaryCards data={requestLogs.data} />
      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg shadow-none">
        <CardHeader className="flex flex-row items-center justify-between gap-3 px-5 py-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-bold leading-6">{t("requestLogs.requestsTitle")}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {requestLogs.isPending
                ? t("common.loading")
                : t("requestLogs.rows", { count: formatNumber(requestLogs.data?.total_count ?? 0) })}
            </p>
          </div>
          {requestLogs.isFetching ? <Loader2 className="shrink-0 animate-spin text-muted-foreground" size={18} /> : null}
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col overflow-hidden p-0">
          {requestLogs.error ? (
            <div className="flex min-h-0 flex-1 items-center justify-center px-4 text-sm text-destructive">
              {formatAppError(requestLogs.error)}
            </div>
          ) : requestLogs.isPending ? (
            <div className="flex min-h-0 flex-1 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 animate-spin" size={18} />
              {t("common.loading")}
            </div>
          ) : logs.length ? (
            <div className="min-h-0 flex-1 overflow-auto">
              <table className="w-full min-w-[1080px] table-fixed border-collapse text-sm">
                <colgroup>
                  <col className="w-[170px]" />
                  <col className="w-[180px]" />
                  <col className="w-[210px]" />
                  <col className="w-[130px]" />
                  <col className="w-[150px]" />
                  <col className="w-[120px]" />
                  <col className="w-[170px]" />
                </colgroup>
                <thead className="sticky top-0 z-10 border-b bg-white text-xs font-bold uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left">{t("requestLogs.time")}</th>
                    <th className="px-4 py-3 text-left">{t("requestLogs.account")}</th>
                    <th className="px-4 py-3 text-left">{t("requestLogs.billingModel")}</th>
                    <th className="px-4 py-3 text-right">{t("usage.input")}</th>
                    <th className="px-4 py-3 text-right">{t("usage.cacheHit")}</th>
                    <th className="px-4 py-3 text-right">{t("usage.output")}</th>
                    <th className="px-4 py-3 text-right">{t("requestLogs.totalCostColumn")}</th>
                  </tr>
                </thead>
                <tbody className={cn("bg-white transition-opacity", requestLogs.isFetching ? "opacity-70" : "")}>
                  {logs.map((log) => (
                    <RequestLogRow key={log.id} log={log} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground">
              {t("requestLogs.noLogsInRange")}
            </div>
          )}
          <div className="flex shrink-0 items-center justify-center border-t p-3">
            <div className="inline-flex items-center gap-2 bg-white">
              <Button
                aria-label={t("common.previousPage")}
                title={t("common.previousPage")}
                variant="secondary"
                size="icon"
                className="h-9 w-9 rounded-lg"
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                disabled={page === 1 || requestLogs.isFetching}
              >
                <ChevronLeft size={16} />
              </Button>
              <PageSelector
                page={page}
                totalPages={totalPages}
                disabled={requestLogs.isFetching}
                jumping={requestLogs.isFetching}
                buttonClassName="h-9 w-32 rounded-md px-3 text-center text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
                onSelect={selectPage}
              />
              <Button
                aria-label={t("common.nextPage")}
                title={t("common.nextPage")}
                variant="secondary"
                size="icon"
                className="h-9 w-9 rounded-lg"
                onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                disabled={page >= totalPages || requestLogs.isFetching}
              >
                <ChevronRight size={16} />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
