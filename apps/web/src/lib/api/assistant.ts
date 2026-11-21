import { apiGet, apiPostJson, isRecord, UnexpectedResponseError } from "@/lib/api/client";

export type AssistantState =
  | "needs_information"
  | "generating"
  | "draft_ready"
  | "unavailable"
  | "error";

export interface AssistantStatus {
  aiEnabled: boolean;
  aiReady: boolean;
  provider: string;
  model: string | null;
  message: string;
}

export interface AssistantMessage {
  id: string;
  role: string;
  content: string;
  createdAt: string;
}

export interface AssistantDraft {
  id: string;
  content: string;
  category: string | null;
  confirmedFacts: Record<string, unknown>;
  suggestedDetails: Record<string, unknown>;
  assumptions: unknown;
  proposedScheduledAt: string | null;
  timezone: string | null;
  status: string;
  version: number;
  label: string;
  createdAt: string;
  updatedAt: string;
}

export interface AssistantThreadSummary {
  id: string;
  status: string;
  title: string | null;
  createdAt: string;
  updatedAt: string;
  responseState: AssistantState | null;
}

export interface AssistantThreadDetail {
  id: string;
  status: string;
  title: string | null;
  createdAt: string;
  updatedAt: string;
  messages: AssistantMessage[];
  draft: AssistantDraft | null;
  clarificationQuestions: string[];
  responseState: AssistantState;
  assistantReady: boolean;
}

export interface AssistantTurn {
  threadId: string;
  state: AssistantState;
  assistantMessage: AssistantMessage | null;
  clarificationQuestions: string[];
  draft: AssistantDraft | null;
  proposedScheduledAt: string | null;
  timezone: string | null;
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new UnexpectedResponseError(`Missing string field: ${field}`);
  }
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseMessage(payload: unknown): AssistantMessage {
  if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid assistant message.");
  return {
    id: requireString(payload.id, "id"),
    role: requireString(payload.role, "role"),
    content: requireString(payload.content, "content"),
    createdAt: requireString(payload.created_at, "created_at"),
  };
}

function parseDraft(payload: unknown): AssistantDraft | null {
  if (payload === null || payload === undefined) return null;
  if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid assistant draft.");
  return {
    id: requireString(payload.id, "id"),
    content: requireString(payload.content, "content"),
    category: optionalString(payload.category),
    confirmedFacts: isRecord(payload.confirmed_facts) ? payload.confirmed_facts : {},
    suggestedDetails: isRecord(payload.suggested_details) ? payload.suggested_details : {},
    assumptions: payload.assumptions ?? {},
    proposedScheduledAt: optionalString(payload.proposed_scheduled_at),
    timezone: optionalString(payload.timezone),
    status: requireString(payload.status, "status"),
    version: typeof payload.version === "number" ? payload.version : 1,
    label: optionalString(payload.label) ?? "Draft — not scheduled",
    createdAt: requireString(payload.created_at, "created_at"),
    updatedAt: requireString(payload.updated_at, "updated_at"),
  };
}

function parseStatus(payload: unknown): AssistantStatus {
  if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid assistant status.");
  return {
    aiEnabled: Boolean(payload.ai_enabled),
    aiReady: Boolean(payload.ai_ready),
    provider: requireString(payload.provider, "provider"),
    model: optionalString(payload.model),
    message: requireString(payload.message, "message"),
  };
}

function parseThreadDetail(payload: unknown): AssistantThreadDetail {
  if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid assistant thread.");
  const messages = Array.isArray(payload.messages) ? payload.messages.map(parseMessage) : [];
  return {
    id: requireString(payload.id, "id"),
    status: requireString(payload.status, "status"),
    title: optionalString(payload.title),
    createdAt: requireString(payload.created_at, "created_at"),
    updatedAt: requireString(payload.updated_at, "updated_at"),
    messages,
    draft: parseDraft(payload.draft),
    clarificationQuestions: Array.isArray(payload.clarification_questions)
      ? payload.clarification_questions.filter((q): q is string => typeof q === "string")
      : [],
    responseState: requireString(payload.response_state, "response_state") as AssistantState,
    assistantReady: Boolean(payload.assistant_ready),
  };
}

function parseThreadList(payload: unknown): AssistantThreadSummary[] {
  if (!Array.isArray(payload)) throw new UnexpectedResponseError("Invalid thread list.");
  return payload.map((item) => {
    if (!isRecord(item)) throw new UnexpectedResponseError("Invalid thread summary.");
    return {
      id: requireString(item.id, "id"),
      status: requireString(item.status, "status"),
      title: optionalString(item.title),
      createdAt: requireString(item.created_at, "created_at"),
      updatedAt: requireString(item.updated_at, "updated_at"),
      responseState: (optionalString(item.response_state) as AssistantState | null) ?? null,
    };
  });
}

function parseTurn(payload: unknown): AssistantTurn {
  if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid assistant turn.");
  return {
    threadId: requireString(payload.thread_id, "thread_id"),
    state: requireString(payload.state, "state") as AssistantState,
    assistantMessage: payload.assistant_message ? parseMessage(payload.assistant_message) : null,
    clarificationQuestions: Array.isArray(payload.clarification_questions)
      ? payload.clarification_questions.filter((q): q is string => typeof q === "string")
      : [],
    draft: parseDraft(payload.draft),
    proposedScheduledAt: optionalString(payload.proposed_scheduled_at),
    timezone: optionalString(payload.timezone),
  };
}

export async function getAssistantStatus(signal?: AbortSignal): Promise<AssistantStatus> {
  return apiGet("/api/v1/assistant/status", parseStatus, {
    signal,
    credentials: "include",
  });
}

export async function createAssistantThread(
  body: { timezone?: string; title?: string },
  signal?: AbortSignal,
): Promise<AssistantThreadDetail> {
  return apiPostJson("/api/v1/assistant/threads", parseThreadDetail, {
    signal,
    body,
  });
}

export async function listAssistantThreads(signal?: AbortSignal): Promise<AssistantThreadSummary[]> {
  return apiGet("/api/v1/assistant/threads", parseThreadList, {
    signal,
    credentials: "include",
  });
}

export async function getAssistantThread(
  threadId: string,
  signal?: AbortSignal,
): Promise<AssistantThreadDetail> {
  return apiGet(`/api/v1/assistant/threads/${threadId}`, parseThreadDetail, {
    signal,
    credentials: "include",
  });
}

export async function postAssistantMessage(
  threadId: string,
  body: { content: string; timezone?: string },
  signal?: AbortSignal,
): Promise<AssistantTurn> {
  return apiPostJson(`/api/v1/assistant/threads/${threadId}/messages`, parseTurn, {
    signal,
    body,
  });
}
