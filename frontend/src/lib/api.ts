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
  id: string | null;
  line_no: number | null;
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
  raw_event_count: number;
  event_count: number;
};

export type SessionEventPreview = {
  id: string;
  line_no: number;
  kind: string;
  timestamp: string | null;
  title?: string | null;
  name?: string | null;
  body_preview: string;
  body_truncated: boolean;
  body_bytes: number;
};

export type SessionEventsResponse = {
  items: SessionEventPreview[];
  next_cursor: string | null;
  raw_event_count: number | null;
  event_count: number | null;
};

export type SessionEventsParams = {
  cursor?: string | null;
  limit?: number;
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

const REQUEST_TIMEOUT_MS = 10_000;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const handleAbort = () => controller.abort();
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  if (init?.signal) {
    if (init.signal.aborted) {
      handleAbort();
    } else {
      init.signal.addEventListener("abort", handleAbort, { once: true });
    }
  }

  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
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
  } catch (error) {
    if (timedOut) {
      throw Object.assign(new Error(`Request timed out after ${REQUEST_TIMEOUT_MS / 1000} seconds`), {
        status: 408,
      });
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
    init?.signal?.removeEventListener("abort", handleAbort);
  }
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
  sessions: ({ query = "", cursor = null, limit = 7 }: SessionListParams = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (query.trim()) params.set("query", query.trim());
    if (cursor) params.set("cursor", cursor);
    return request<SessionListResponse>(`/api/sessions?${params.toString()}`);
  },
  sessionDetail: (threadId: string) =>
    request<SessionDetail>(`/api/sessions/${threadId}`),
  sessionEvents: (threadId: string, { cursor = null, limit = 100 }: SessionEventsParams = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set("cursor", cursor);
    return request<SessionEventsResponse>(`/api/sessions/${threadId}/events?${params.toString()}`);
  },
  sessionEvent: (threadId: string, lineNo: number) =>
    request<SessionEvent>(`/api/sessions/${threadId}/events/${lineNo}`),
  usageAggregates: () => request<UsageAggregatesResponse>("/api/usage/aggregates"),
};
