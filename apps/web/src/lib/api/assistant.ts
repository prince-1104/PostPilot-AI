import {
  apiGet,
  apiPatchJson,
  apiPostJson,
  isRecord,
  UnexpectedResponseError,
} from "@/lib/api/client";
import { parseScheduledPost, type ScheduledPost } from "@/lib/api/posts";

export type AssistantState =
  | "needs_information"
  | "generating"
  | "draft_ready"
  | "unavailable"
  | "error";

export type WritingStyle =
  | "professional"
  | "conversational"
  | "concise"
  | "detailed"
  | "promotional";

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
  scheduledPostId: string | null;
  label: string;
  createdAt: string;
  updatedAt: string;
}

export interface AssistantSchedulePreview {
  draftId: string;
  draftVersion: number;
  content: string;
  linkedinConnectionId: string;
  linkedinDisplayName: string | null;
  scheduledAtLocal: string;
  timezone: string;
  scheduledAtUtc: string;
  approvalWarnings: string[];
  advisoryWarnings: string[];
  hardBlockers: string[];
  connectionExpiryWarning: string | null;
  canConfirm: boolean;
  label: string;
}

export interface AssistantScheduleConfirm {
  draftId: string;
  draftVersion: number;
  scheduledPostId: string;
  post: ScheduledPost;
  idempotentReplay: boolean;
  message: string;
}

export interface AssistantThreadSummary {
  id: string;
  status: string;
  title: string | null;
  createdAt: string;
  updatedAt: string;
  responseState: AssistantState | null;
  currentStage: string | null;
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
  currentStage: string | null;
  writingStyle: WritingStyle | null;
  reviewIssues: string[];
  reviewSuggestions: string[];
  validationErrors: string[];
  lockVersion: number;
  assistantReady: boolean;
}

export interface AssistantTurn {
  threadId: string;
  state: AssistantState;
  currentStage: string | null;
  assistantMessage: AssistantMessage | null;
  clarificationQuestions: string[];
  draft: AssistantDraft | null;
  proposedScheduledAt: string | null;
  timezone: string | null;
  writingStyle: WritingStyle | null;
  reviewIssues: string[];
  reviewSuggestions: string[];
  validationErrors: string[];
  lockVersion: number;
  idempotentReplay: boolean;
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

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
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
    scheduledPostId: optionalString(payload.scheduled_post_id),
    label: optionalString(payload.label) ?? "Draft — not scheduled",
    createdAt: requireString(payload.created_at, "created_at"),
    updatedAt: requireString(payload.updated_at, "updated_at"),
  };
}

function parseSchedulePreview(payload: unknown): AssistantSchedulePreview {
  if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid schedule preview.");
  return {
    draftId: requireString(payload.draft_id, "draft_id"),
    draftVersion: typeof payload.draft_version === "number" ? payload.draft_version : 1,
    content: requireString(payload.content, "content"),
    linkedinConnectionId: requireString(payload.linkedin_connection_id, "linkedin_connection_id"),
    linkedinDisplayName: optionalString(payload.linkedin_display_name),
    scheduledAtLocal: requireString(payload.scheduled_at_local, "scheduled_at_local"),
    timezone: requireString(payload.timezone, "timezone"),
    scheduledAtUtc: requireString(payload.scheduled_at_utc, "scheduled_at_utc"),
    approvalWarnings: stringList(payload.approval_warnings),
    advisoryWarnings: stringList(payload.advisory_warnings),
    hardBlockers: stringList(payload.hard_blockers),
    connectionExpiryWarning: optionalString(payload.connection_expiry_warning),
    canConfirm: Boolean(payload.can_confirm),
    label: optionalString(payload.label) ?? "Draft — not scheduled",
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
    clarificationQuestions: stringList(payload.clarification_questions),
    responseState: requireString(payload.response_state, "response_state") as AssistantState,
    currentStage: optionalString(payload.current_stage),
    writingStyle: (optionalString(payload.writing_style) as WritingStyle | null) ?? null,
    reviewIssues: stringList(payload.review_issues),
    reviewSuggestions: stringList(payload.review_suggestions),
    validationErrors: stringList(payload.validation_errors),
    lockVersion: typeof payload.lock_version === "number" ? payload.lock_version : 0,
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
      currentStage: optionalString(item.current_stage),
    };
  });
}

function parseTurn(payload: unknown): AssistantTurn {
  if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid assistant turn.");
  return {
    threadId: requireString(payload.thread_id, "thread_id"),
    state: requireString(payload.state, "state") as AssistantState,
    currentStage: optionalString(payload.current_stage),
    assistantMessage: payload.assistant_message ? parseMessage(payload.assistant_message) : null,
    clarificationQuestions: stringList(payload.clarification_questions),
    draft: parseDraft(payload.draft),
    proposedScheduledAt: optionalString(payload.proposed_scheduled_at),
    timezone: optionalString(payload.timezone),
    writingStyle: (optionalString(payload.writing_style) as WritingStyle | null) ?? null,
    reviewIssues: stringList(payload.review_issues),
    reviewSuggestions: stringList(payload.review_suggestions),
    validationErrors: stringList(payload.validation_errors),
    lockVersion: typeof payload.lock_version === "number" ? payload.lock_version : 0,
    idempotentReplay: Boolean(payload.idempotent_replay),
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
  body: {
    content: string;
    timezone?: string;
    clientMessageId?: string;
    tone?: WritingStyle;
  },
  signal?: AbortSignal,
): Promise<AssistantTurn> {
  return apiPostJson(`/api/v1/assistant/threads/${threadId}/messages`, parseTurn, {
    signal,
    body: {
      content: body.content,
      timezone: body.timezone,
      client_message_id: body.clientMessageId,
      tone: body.tone,
    },
  });
}

export async function patchAssistantDraft(
  threadId: string,
  body: { content: string; expectedVersion: number; expectedLockVersion?: number },
  signal?: AbortSignal,
): Promise<AssistantDraft> {
  const draft = await apiPatchJson(`/api/v1/assistant/threads/${threadId}/draft`, parseDraft, {
    signal,
    body: {
      content: body.content,
      expected_version: body.expectedVersion,
      expected_lock_version: body.expectedLockVersion,
    },
  });
  if (!draft) throw new UnexpectedResponseError("Draft patch returned empty.");
  return draft;
}

export async function runAssistantDraftAction(
  threadId: string,
  body: {
    action: "regenerate" | "rewrite" | "set_tone";
    instruction?: string;
    tone?: WritingStyle;
    expectedVersion?: number;
    clientMessageId?: string;
  },
  signal?: AbortSignal,
): Promise<AssistantTurn> {
  return apiPostJson(`/api/v1/assistant/threads/${threadId}/draft/actions`, parseTurn, {
    signal,
    body: {
      action: body.action,
      instruction: body.instruction,
      tone: body.tone,
      expected_version: body.expectedVersion,
      client_message_id: body.clientMessageId,
    },
  });
}

export async function previewAssistantSchedule(
  draftId: string,
  body: {
    expectedDraftVersion: number;
    content?: string;
    linkedinConnectionId: string;
    scheduledAt: string;
    timezone: string;
    acknowledgeWarnings?: boolean;
  },
  signal?: AbortSignal,
): Promise<AssistantSchedulePreview> {
  return apiPostJson(`/api/v1/assistant/drafts/${draftId}/schedule-preview`, parseSchedulePreview, {
    signal,
    body: {
      expected_draft_version: body.expectedDraftVersion,
      content: body.content,
      linkedin_connection_id: body.linkedinConnectionId,
      scheduled_at: body.scheduledAt,
      timezone: body.timezone,
      acknowledge_warnings: body.acknowledgeWarnings ?? false,
    },
  });
}

export async function confirmAssistantSchedule(
  draftId: string,
  body: {
    expectedDraftVersion: number;
    content: string;
    linkedinConnectionId: string;
    scheduledAt: string;
    timezone: string;
    acknowledgeWarnings?: boolean;
  },
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<AssistantScheduleConfirm> {
  return apiPostJson(
    `/api/v1/assistant/drafts/${draftId}/schedule`,
    (payload: unknown) => {
      if (!isRecord(payload)) throw new UnexpectedResponseError("Invalid schedule confirm.");
      return {
        draftId: requireString(payload.draft_id, "draft_id"),
        draftVersion: typeof payload.draft_version === "number" ? payload.draft_version : 1,
        scheduledPostId: requireString(payload.scheduled_post_id, "scheduled_post_id"),
        post: parseScheduledPost(payload.post),
        idempotentReplay: Boolean(payload.idempotent_replay),
        message: optionalString(payload.message) ?? "Scheduled.",
      };
    },
    {
      signal,
      headers: { "Idempotency-Key": idempotencyKey },
      body: {
        expected_draft_version: body.expectedDraftVersion,
        content: body.content,
        linkedin_connection_id: body.linkedinConnectionId,
        scheduled_at: body.scheduledAt,
        timezone: body.timezone,
        confirm_schedule: true,
        acknowledge_warnings: body.acknowledgeWarnings ?? false,
      },
    },
  );
}
