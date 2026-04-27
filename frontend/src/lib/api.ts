export type LimitDTO = {
  used_percent: number | null;
  remaining_percent: number;
  window_minutes: number | null;
  resets_at: number | null;
};

export type AccountDTO = {
  account_id: string;
  display_name: string;
  custom_name: string | null;
  current: boolean;
  hidden: boolean;
  plan_type: string | null;
  five_hour: LimitDTO | null;
  weekly: LimitDTO | null;
  last_scanned_at: number | null;
  last_error: string | null;
};

export type ScanResult = {
  account: AccountDTO;
  status: "ok" | "error";
  error: string | null;
};

export type SessionSummary = {
  thread_id: string;
  title: string;
  cwd: string;
  model_provider: string;
  model: string | null;
  created_at: number | null;
  updated_at: number | null;
  tokens_used: number;
  archived: boolean;
};

export type SessionListResponse = {
  items: SessionSummary[];
  next_cursor: string | null;
  total_count: number;
};

export type SessionListParams = {
  query?: string;
  cursor?: string | null;
  limit?: number;
};

export type SessionEvent = {
  kind: string;
  timestamp: string | null;
  title?: string | null;
  text?: string | null;
  name?: string | null;
  arguments?: unknown;
  data?: unknown;
};

export type SessionDetail = {
  summary: SessionSummary;
  events: SessionEvent[];
  raw_event_count: number;
};

export type UsageBucket = "hour" | "day" | "week";

export type UsageAggregatePointDTO = {
  bucket_start: number;
  bucket_end: number;
  input_tokens: number;
  cache_creation_tokens: number;
  cache_hit_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
  cost_usd: number | null;
  cost_known: boolean;
  unknown_cost_events: number;
  event_count: number;
};

export type UsageRangeAggregateDTO = {
  range_key: string;
  bucket: UsageBucket;
  range_start: number;
  range_end: number;
  event_count: number;
  items: UsageAggregatePointDTO[];
};

export type UsageAggregatesResponse = {
  generated_at: number;
  ranges: Record<string, UsageRangeAggregateDTO>;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const message = detail?.detail ?? response.statusText;
    throw Object.assign(new Error(message), { status: response.status });
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (password: string) =>
    request<{ ok: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  accounts: () => request<AccountDTO[]>("/api/accounts"),
  scan: () => request<ScanResult>("/api/accounts/scan", { method: "POST" }),
  hideAccount: (accountId: string) =>
    request<{ ok: boolean }>(`/api/accounts/${accountId}/hide`, { method: "POST" }),
  renameAccount: (accountId: string, customName: string | null) =>
    request<AccountDTO>(`/api/accounts/${accountId}/name`, {
      method: "POST",
      body: JSON.stringify({ custom_name: customName }),
    }),
  sessions: ({ query = "", cursor = null, limit = 30 }: SessionListParams = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (query.trim()) params.set("query", query.trim());
    if (cursor) params.set("cursor", cursor);
    return request<SessionListResponse>(`/api/sessions?${params.toString()}`);
  },
  sessionDetail: (threadId: string) =>
    request<SessionDetail>(`/api/sessions/${threadId}`),
  usageAggregates: () => request<UsageAggregatesResponse>("/api/usage/aggregates"),
};
