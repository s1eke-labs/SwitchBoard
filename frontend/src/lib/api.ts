export type LimitDTO = {
  used_percent: number | null;
  remaining_percent: number;
  window_minutes: number | null;
  resets_at: number | null;
};

export type IssueDetail = {
  code: string;
  message: string;
};

export type AccountDTO = {
  account_id: string;
  display_name: string;
  custom_name: string | null;
  user_name: string | null;
  current: boolean;
  hidden: boolean;
  plan_type: string | null;
  five_hour: LimitDTO | null;
  weekly: LimitDTO | null;
  last_scanned_at: number | null;
  last_error: string | null;
  failed_scan_count: number;
  expired: boolean;
  usage_started_at: number;
  usage_ended_at: number | null;
  usage_seconds: number;
};

export type ScanResult = {
  account: AccountDTO;
  status: "ok" | "error";
  warning: IssueDetail | null;
};

export type SwitchBoardConfigAccountDTO = {
  account_id: string;
  display_name: string;
  custom_name: string | null;
  hidden: boolean;
  user_name: string | null;
  plan_type: string | null;
  expired: boolean;
  current: boolean;
  last_scanned_at: number | null;
  five_hour: SwitchBoardConfigLimitDTO | null;
  weekly: SwitchBoardConfigLimitDTO | null;
};

export type SwitchBoardConfigLimitDTO = {
  remaining_percent: number;
  window_minutes: number | null;
  resets_at: number | null;
};

export type SwitchBoardConfigExportDTO = {
  schema: "switchboard.config.v1";
  exported_at: number;
  accounts: SwitchBoardConfigAccountDTO[];
};

export type SwitchBoardConfigImportSummary = {
  ok: boolean;
  imported: number;
  created: number;
  updated: number;
  skipped: number;
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
  page?: number;
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

export type SessionUserIndexItem = {
  id: string;
  line_no: number;
  event_index: number;
  timestamp: string | null;
  body_preview: string;
  body_bytes: number;
};

export type SessionUserIndexResponse = {
  items: SessionUserIndexItem[];
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

export type UsageRequestLogDTO = {
  id: string;
  thread_id: string;
  event_index: number;
  account_id: string | null;
  account_display_name: string | null;
  occurred_at: number;
  billing_model: string | null;
  input_tokens: number;
  cache_creation_tokens: number;
  cache_hit_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
  total_cost_usd: number | null;
  cost_known: boolean;
};

export type UsageRequestLogsResponse = {
  items: UsageRequestLogDTO[];
  next_cursor: string | null;
  total_count: number;
  summary: {
    request_count: number;
    input_tokens: number;
    cache_creation_tokens: number;
    cache_hit_tokens: number;
    output_tokens: number;
    reasoning_output_tokens: number;
    total_tokens: number;
    total_cost_usd: number | null;
    cost_known: boolean;
    unknown_cost_events: number;
  };
};

export type UsageRequestLogsParams = {
  from?: number;
  to?: number;
  account_id?: string;
  cursor?: string | null;
  page?: number;
  limit?: number;
};

export type ImageGenerationRequest = {
  prompt: string;
  model?: string;
  size?:
    | "1024x1024"
    | "1536x1536"
    | "2880x2880"
    | "768x1024"
    | "1536x2048"
    | "2448x3264"
    | "1024x768"
    | "2048x1536"
    | "3264x2448"
    | "720x1280"
    | "1152x2048"
    | "2160x3840"
    | "1280x720"
    | "2048x1152"
    | "3840x2160"
    | "1344x576"
    | "2688x1152"
    | "3360x1440";
  quality?: "auto";
  n?: 1 | 2 | 4;
  response_format?: "b64_json" | "url";
  reference_images?: ImageReferenceInput[];
  conversation_id?: string | null;
  previous_response_id?: string | null;
};

export type ImageReferenceInput = {
  file_name: string;
  mime_type: string;
  b64_json: string;
};

export type ImageReferenceData = {
  id: string;
  file_name: string;
  file_url: string;
  original_file_name: string;
  mime_type: string;
  size_bytes: number;
};

export type ImageGenerationResponse = {
  created: number;
  model: string;
  response_id: string | null;
  data: Array<{
    b64_json: string | null;
    url: string | null;
    revised_prompt: string | null;
    file_name: string | null;
    file_url: string | null;
    saved_path: string | null;
  }>;
};

export type ImageGenerationJobStatus = "queued" | "running" | "succeeded" | "failed";

export type ImageGenerationJob = {
  id: string;
  conversation_id: string | null;
  prompt: string;
  size: NonNullable<ImageGenerationRequest["size"]> | "auto" | "1024x1536" | "1536x1024";
  quality: "auto" | "low" | "medium" | "high";
  n: 1 | 2 | 4;
  status: ImageGenerationJobStatus;
  created_at: number;
  updated_at: number;
  previous_response_id: string | null;
  upstream_response_id: string | null;
  position: number | null;
  references: ImageReferenceData[];
  result: ImageGenerationResponse | null;
  error: IssueDetail | null;
};

export type ImageGenerationJobListResponse = {
  items: ImageGenerationJob[];
  total_count: number;
};

const REQUEST_TIMEOUT_MS = 10_000;
const IMAGE_REQUEST_TIMEOUT_MS = 300_000;

export class ApiError extends Error {
  status: number;
  code: string | null;
  detail: unknown;

  constructor({
    message,
    status,
    code = null,
    detail = null,
  }: {
    message: string;
    status: number;
    code?: string | null;
    detail?: unknown;
  }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function isIssueDetail(value: unknown): value is IssueDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    typeof value.code === "string" &&
    "message" in value &&
    typeof value.message === "string"
  );
}

function parseErrorDetail(payload: unknown, statusText: string) {
  const fallbackMessage = statusText || "Request failed";
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = payload.detail;
    if (isIssueDetail(detail)) {
      return {
        message: detail.message,
        code: detail.code,
        detail,
      };
    }
    if (typeof detail === "string") {
      return {
        message: detail,
        code: null,
        detail,
      };
    }
  }
  if (isIssueDetail(payload)) {
    return {
      message: payload.message,
      code: payload.code,
      detail: payload,
    };
  }
  return {
    message: fallbackMessage,
    code: null,
    detail: payload,
  };
}

async function request<T>(
  url: string,
  init?: RequestInit,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const handleAbort = () => controller.abort();
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

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
      const payload = await response.json().catch(() => ({}));
      const detail = parseErrorDetail(payload, response.statusText);
      throw new ApiError({
        message: detail.message,
        status: response.status,
        code: detail.code,
        detail: detail.detail,
      });
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (timedOut) {
      throw new ApiError({
        message: `Request timed out after ${timeoutMs / 1000} seconds`,
        status: 408,
        code: "CLIENT_REQUEST_TIMEOUT",
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
  switchAccount: (accountId: string) =>
    request<ScanResult>(`/api/accounts/${accountId}/switch`, { method: "POST" }),
  hideAccount: (accountId: string) =>
    request<{ ok: boolean }>(`/api/accounts/${accountId}/hide`, { method: "POST" }),
  renameAccount: (accountId: string, customName: string | null) =>
    request<AccountDTO>(`/api/accounts/${accountId}/name`, {
      method: "POST",
      body: JSON.stringify({ custom_name: customName }),
    }),
  exportConfig: () => request<SwitchBoardConfigExportDTO>("/api/config/export"),
  importConfig: (config: unknown) =>
    request<SwitchBoardConfigImportSummary>("/api/config/import", {
      method: "POST",
      body: JSON.stringify(config),
    }),
  sessions: ({ query = "", cursor = null, page, limit = 7 }: SessionListParams = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (query.trim()) params.set("query", query.trim());
    if (cursor) params.set("cursor", cursor);
    if (page !== undefined) params.set("page", String(page));
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
  sessionUserIndex: (threadId: string) =>
    request<SessionUserIndexResponse>(`/api/sessions/${threadId}/user-index`),
  usageAggregates: () => request<UsageAggregatesResponse>("/api/usage/aggregates"),
  usageRequestLogs: ({ from, to, account_id, cursor = null, page, limit = 50 }: UsageRequestLogsParams = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (from !== undefined) params.set("from", String(from));
    if (to !== undefined) params.set("to", String(to));
    if (account_id) params.set("account_id", account_id);
    if (cursor) params.set("cursor", cursor);
    if (page !== undefined) params.set("page", String(page));
    return request<UsageRequestLogsResponse>(`/api/usage/request-logs?${params.toString()}`);
  },
  generateImage: (payload: ImageGenerationRequest) =>
    request<ImageGenerationResponse>(
      "/api/images/generations",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      { timeoutMs: IMAGE_REQUEST_TIMEOUT_MS },
    ),
  createImageJob: (payload: ImageGenerationRequest) =>
    request<ImageGenerationJob>("/api/images/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  imageJobs: ({ page = 1, limit = 20 }: { page?: number; limit?: number } = {}) =>
    request<ImageGenerationJobListResponse>(`/api/images/jobs?page=${page}&limit=${limit}`),
  imageJob: (jobId: string) => request<ImageGenerationJob>(`/api/images/jobs/${jobId}`),
};
