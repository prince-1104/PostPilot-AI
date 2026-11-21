import { apiGet, isRecord } from "@/lib/api/client";

export interface AiAnalyticsSummary {
  from_time: string;
  to_time: string;
  total_llm_requests: number;
  successful_llm_requests: number;
  failed_llm_requests: number;
  total_input_tokens: number | null;
  total_output_tokens: number | null;
  total_cached_input_tokens: number | null;
  usage_known_requests: number;
  usage_unknown_requests: number;
  total_estimated_cost: number | null;
  cost_currency: string;
  cost_label: string;
  cost_available_requests: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  review_traces: number;
  review_failures: number;
  review_failure_rate: number | null;
  automatic_revision_traces: number;
  drafts_generated: number;
  approved_ai_drafts_scheduled: number;
  requests_by_model: Array<Record<string, unknown>>;
  cost_per_user: Array<Record<string, unknown>>;
  cost_per_conversation: Array<Record<string, unknown>>;
}

export interface ThreadInspection {
  thread_id: string;
  user_id: string;
  title: string | null;
  status: string;
  message_count: number;
  draft_version: number | null;
  draft_status: string | null;
  scheduled_post_id: string | null;
  schedule_ops: Array<Record<string, unknown>>;
  traces: Array<Record<string, unknown>>;
  usage_events: Array<Record<string, unknown>>;
  note: string;
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function numOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord);
}

function parseSummary(payload: unknown): AiAnalyticsSummary {
  if (!isRecord(payload)) {
    throw new Error("Invalid AI analytics payload");
  }
  return {
    from_time: str(payload.from_time),
    to_time: str(payload.to_time),
    total_llm_requests: num(payload.total_llm_requests),
    successful_llm_requests: num(payload.successful_llm_requests),
    failed_llm_requests: num(payload.failed_llm_requests),
    total_input_tokens: numOrNull(payload.total_input_tokens),
    total_output_tokens: numOrNull(payload.total_output_tokens),
    total_cached_input_tokens: numOrNull(payload.total_cached_input_tokens),
    usage_known_requests: num(payload.usage_known_requests),
    usage_unknown_requests: num(payload.usage_unknown_requests),
    total_estimated_cost: numOrNull(payload.total_estimated_cost),
    cost_currency: str(payload.cost_currency, "USD"),
    cost_label: str(payload.cost_label, "estimate"),
    cost_available_requests: num(payload.cost_available_requests),
    avg_latency_ms: numOrNull(payload.avg_latency_ms),
    p95_latency_ms: numOrNull(payload.p95_latency_ms),
    review_traces: num(payload.review_traces),
    review_failures: num(payload.review_failures),
    review_failure_rate: numOrNull(payload.review_failure_rate),
    automatic_revision_traces: num(payload.automatic_revision_traces),
    drafts_generated: num(payload.drafts_generated),
    approved_ai_drafts_scheduled: num(payload.approved_ai_drafts_scheduled),
    requests_by_model: recordList(payload.requests_by_model),
    cost_per_user: recordList(payload.cost_per_user),
    cost_per_conversation: recordList(payload.cost_per_conversation),
  };
}

function parseInspection(payload: unknown): ThreadInspection {
  if (!isRecord(payload)) {
    throw new Error("Invalid thread inspection payload");
  }
  return {
    thread_id: str(payload.thread_id),
    user_id: str(payload.user_id),
    title: typeof payload.title === "string" ? payload.title : null,
    status: str(payload.status),
    message_count: num(payload.message_count),
    draft_version: numOrNull(payload.draft_version),
    draft_status: typeof payload.draft_status === "string" ? payload.draft_status : null,
    scheduled_post_id:
      typeof payload.scheduled_post_id === "string" ? payload.scheduled_post_id : null,
    schedule_ops: recordList(payload.schedule_ops),
    traces: recordList(payload.traces),
    usage_events: recordList(payload.usage_events),
    note: str(payload.note),
  };
}

export function getAiAnalytics(
  preset: "24h" | "7d" | "30d",
  signal?: AbortSignal,
): Promise<AiAnalyticsSummary> {
  return apiGet(`/api/v1/admin/ai/analytics?preset=${preset}`, parseSummary, {
    credentials: "include",
    signal,
  });
}

export function inspectAiThread(
  threadId: string,
  signal?: AbortSignal,
): Promise<ThreadInspection> {
  return apiGet(`/api/v1/admin/ai/threads/${threadId}`, parseInspection, {
    credentials: "include",
    signal,
  });
}
