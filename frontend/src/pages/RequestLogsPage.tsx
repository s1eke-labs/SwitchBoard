import { ReactNode, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Database, DollarSign, Layers3, ReceiptText, UserRound } from "lucide-react";
import { AccountDTO, api, UsageRequestLogDTO, UsageRequestLogsResponse } from "@/lib/api";
import { getCurrentLocale, translate, useI18n } from "@/i18n";
import { formatAppError } from "@/lib/errors";
import { cn, formatNumber, formatTime } from "@/lib/utils";
import { PageSelector } from "@/components/PageSelector";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { Badge } from "@/components/heroui/badge";
import { Table } from "@/components/heroui/table";
import { Select } from "@/components/heroui/select";
import { Spinner } from "@/components/heroui/spinner";
import { SegmentedControl } from "@/components/heroui/toggle-button-group";

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
    <Select
      aria-label={t("requestLogs.accountFilter")}
      className="w-64 max-w-full"
      fullWidth={false}
      selectedKey={value}
      isDisabled={disabled}
      onSelectionChange={(key) => {
        if (typeof key === "string") onChange(key);
      }}
    >
      <Select.Trigger>
        <span className="inline-flex min-w-0 items-center gap-2">
          <UserRound size={15} className="shrink-0 text-muted-foreground" />
          <span className="truncate">{label}</span>
        </span>
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <Select.ListBox aria-label={t("requestLogs.accountFilter")}>
          {options.map((option) => (
            <Select.Item key={option.value} id={option.value}>
              <span className="truncate">{option.label}</span>
            </Select.Item>
          ))}
        </Select.ListBox>
      </Select.Popover>
    </Select>
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
    <Table.Row id={log.id} className="border-b last:border-b-0">
      <Table.Cell className="whitespace-nowrap px-4 py-3 align-top text-sm font-medium text-foreground">
        {formatTime(log.occurred_at)}
      </Table.Cell>
      <Table.Cell className="px-4 py-3 align-top">
        <Badge className="max-w-full truncate" tone={log.account_id ? "blue" : "neutral"}>
          {log.account_display_name ?? translate("requestLogs.unassigned")}
        </Badge>
      </Table.Cell>
      <Table.Cell className="px-4 py-3 align-top">
        <Badge className="max-w-full truncate" tone="neutral">
          {log.billing_model ?? translate("common.unknown")}
        </Badge>
      </Table.Cell>
      <Table.Cell className="px-4 py-3 align-top text-right tabular-nums">
        <div className="font-semibold text-foreground">{formatNumber(log.input_tokens)}</div>
      </Table.Cell>
      <Table.Cell className="px-4 py-3 align-top text-right tabular-nums">
        <div className="font-semibold text-foreground">{formatNumber(log.cache_hit_tokens)}</div>
      </Table.Cell>
      <Table.Cell className="px-4 py-3 align-top text-right tabular-nums">
        <div className="font-semibold text-foreground">{formatNumber(log.output_tokens)}</div>
      </Table.Cell>
      <Table.Cell className="whitespace-nowrap px-4 py-3 text-right align-top tabular-nums">
        <div className="font-semibold text-foreground">{formatUsd(log.total_cost_usd, log.cost_known)}</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {translate("requestLogs.tokensWithCount", { count: formatNumber(log.total_tokens) })}
        </div>
      </Table.Cell>
    </Table.Row>
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
          <SegmentedControl
            aria-label={t("requestLogs.title")}
            value={range}
            options={(Object.keys(ranges) as RangeKey[]).map((key) => ({ value: key, label: ranges[key].label }))}
            disabled={requestLogs.isFetching}
            onChange={selectRange}
          />
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
          {requestLogs.isFetching ? <Spinner className="text-muted-foreground" /> : null}
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col overflow-hidden p-0">
          {requestLogs.error ? (
            <div className="flex min-h-0 flex-1 items-center justify-center px-4 text-sm text-destructive">
              {formatAppError(requestLogs.error)}
            </div>
          ) : requestLogs.isPending ? (
            <div className="flex min-h-0 flex-1 items-center justify-center text-muted-foreground">
              <Spinner className="mr-2" />
              {t("common.loading")}
            </div>
          ) : logs.length ? (
            <div className="min-h-0 flex-1 overflow-auto">
              <Table variant="secondary" className="min-w-[1080px] bg-white">
                <Table.ScrollContainer className="overflow-visible">
                  <Table.Content aria-label={t("requestLogs.requestsTitle")} className="w-full table-fixed border-collapse text-sm">
                    <Table.Header className="sticky top-0 z-10 border-b bg-white text-xs font-bold uppercase text-muted-foreground">
                      <Table.Column id="time" isRowHeader className="w-[170px] px-4 py-3 text-left">
                        {t("requestLogs.time")}
                      </Table.Column>
                      <Table.Column id="account" className="w-[180px] px-4 py-3 text-left">
                        {t("requestLogs.account")}
                      </Table.Column>
                      <Table.Column id="billingModel" className="w-[210px] px-4 py-3 text-left">
                        {t("requestLogs.billingModel")}
                      </Table.Column>
                      <Table.Column id="input" className="w-[130px] px-4 py-3 text-right">
                        {t("usage.input")}
                      </Table.Column>
                      <Table.Column id="cacheHit" className="w-[150px] px-4 py-3 text-right">
                        {t("usage.cacheHit")}
                      </Table.Column>
                      <Table.Column id="output" className="w-[120px] px-4 py-3 text-right">
                        {t("usage.output")}
                      </Table.Column>
                      <Table.Column id="totalCost" className="w-[170px] px-4 py-3 text-right">
                        {t("requestLogs.totalCostColumn")}
                      </Table.Column>
                    </Table.Header>
                    <Table.Body className={cn("bg-white transition-opacity", requestLogs.isFetching ? "opacity-70" : "")}>
                      {logs.map((log) => (
                        <RequestLogRow key={log.id} log={log} />
                      ))}
                    </Table.Body>
                  </Table.Content>
                </Table.ScrollContainer>
              </Table>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground">
              {t("requestLogs.noLogsInRange")}
            </div>
          )}
          <div className="flex shrink-0 items-center justify-center border-t p-3">
            <PageSelector
              page={page}
              totalPages={totalPages}
              disabled={requestLogs.isFetching}
              jumping={requestLogs.isFetching}
              onSelect={selectPage}
            />
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
