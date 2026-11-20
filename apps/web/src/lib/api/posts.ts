import { apiGet, apiPatchJson, apiPostJson, isRecord } from "@/lib/api/client";

export type PostStatus =
  | "scheduled"
  | "processing"
  | "published"
  | "failed"
  | "cancelled";

export interface ScheduledPost {
  id: string;
  linkedinConnectionId: string;
  content: string;
  scheduledAt: string;
  timezone: string;
  status: PostStatus;
  version: number;
  createdAt: string;
  updatedAt: string;
  publishedAt: string | null;
  connectionExpiresBeforeSchedule: boolean;
  connectionExpiryWarning: string | null;
}

export interface ScheduledPostList {
  items: ScheduledPost[];
  nextCursor: string | null;
}

export interface CreateScheduledPostInput {
  content: string;
  scheduledAt: string;
  timezone: string;
  linkedinConnectionId: string;
}

export interface UpdateScheduledPostInput {
  expectedVersion: number;
  content?: string;
  scheduledAt?: string;
  timezone?: string;
}

const POST_STATUSES: ReadonlySet<string> = new Set([
  "scheduled",
  "processing",
  "published",
  "failed",
  "cancelled",
]);

function requireString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Scheduled post response missing string field: ${field}`);
  }
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function parseScheduledPost(payload: unknown): ScheduledPost {
  if (!isRecord(payload)) {
    throw new Error("Scheduled post response was not an object.");
  }

  const status = requireString(payload.status, "status");
  if (!POST_STATUSES.has(status)) {
    throw new Error(`Unknown post status: ${status}`);
  }

  const version = payload.version;
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1) {
    throw new Error("Scheduled post response had an invalid version.");
  }

  return {
    id: requireString(payload.id, "id"),
    linkedinConnectionId: requireString(payload.linkedin_connection_id, "linkedin_connection_id"),
    content: requireString(payload.content, "content"),
    scheduledAt: requireString(payload.scheduled_at, "scheduled_at"),
    timezone: requireString(payload.timezone, "timezone"),
    status: status as PostStatus,
    version,
    createdAt: requireString(payload.created_at, "created_at"),
    updatedAt: requireString(payload.updated_at, "updated_at"),
    publishedAt: optionalString(payload.published_at),
    connectionExpiresBeforeSchedule: Boolean(payload.connection_expires_before_schedule),
    connectionExpiryWarning: optionalString(payload.connection_expiry_warning),
  };
}

function parseScheduledPostList(payload: unknown): ScheduledPostList {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw new Error("Scheduled post list response was invalid.");
  }
  return {
    items: payload.items.map(parseScheduledPost),
    nextCursor: typeof payload.next_cursor === "string" ? payload.next_cursor : null,
  };
}

export interface ListPostsParams {
  status?: PostStatus | "";
  cursor?: string | null;
  limit?: number;
  signal?: AbortSignal;
}

export async function listPosts(params: ListPostsParams = {}): Promise<ScheduledPostList> {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.cursor) search.set("cursor", params.cursor);
  if (params.limit) search.set("limit", String(params.limit));
  const query = search.toString();
  return apiGet(`/api/v1/posts${query ? `?${query}` : ""}`, parseScheduledPostList, {
    credentials: "include",
    signal: params.signal,
  });
}

export async function getPost(postId: string, signal?: AbortSignal): Promise<ScheduledPost> {
  return apiGet(`/api/v1/posts/${postId}`, parseScheduledPost, {
    credentials: "include",
    signal,
  });
}

export async function createPost(
  input: CreateScheduledPostInput,
  idempotencyKey: string,
): Promise<ScheduledPost> {
  return apiPostJson("/api/v1/posts", parseScheduledPost, {
    credentials: "include",
    headers: { "Idempotency-Key": idempotencyKey },
    body: {
      content: input.content,
      scheduled_at: input.scheduledAt,
      timezone: input.timezone,
      linkedin_connection_id: input.linkedinConnectionId,
    },
  });
}

export async function updatePost(
  postId: string,
  input: UpdateScheduledPostInput,
): Promise<ScheduledPost> {
  return apiPatchJson(`/api/v1/posts/${postId}`, parseScheduledPost, {
    credentials: "include",
    body: {
      expected_version: input.expectedVersion,
      ...(input.content !== undefined ? { content: input.content } : {}),
      ...(input.scheduledAt !== undefined ? { scheduled_at: input.scheduledAt } : {}),
      ...(input.timezone !== undefined ? { timezone: input.timezone } : {}),
    },
  });
}

export async function cancelPost(postId: string, expectedVersion: number): Promise<ScheduledPost> {
  return apiPostJson(`/api/v1/posts/${postId}/cancel`, parseScheduledPost, {
    credentials: "include",
    body: { expected_version: expectedVersion },
  });
}

/** Stable UUID for one logical create attempt; reuse after network failure. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
