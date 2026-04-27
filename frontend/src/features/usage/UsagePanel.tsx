import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChart3, Loader2 } from "lucide-react";
import { api, UsageAggregatePointDTO } from "@/lib/api";
import { formatChartTime, formatNumber } from "@/lib/utils";
import { useElementSize } from "@/hooks/useElementSize";
import { Card, CardContent } from "@/components/ui/card";

type RangeKey = "24h" | "7d" | "30d" | "90d";

type ChartPoint = UsageAggregatePointDTO & {
  label: string;
};

const ranges: Record<RangeKey, { label: string }> = {
  "24h": { label: "24h" },
  "7d": { label: "7d" },
  "30d": { label: "30d" },
  "90d": { label: "90d" },
};

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

export function UsagePanel() {
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
    <section className="flex h-full min-h-0 flex-col gap-4 overflow-hidden rounded-lg border bg-white p-4 shadow-soft">
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
      <Card className="min-h-0 flex-1 overflow-hidden shadow-none">
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
