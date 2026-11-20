import { apiGet, isRecord } from "@/lib/api/client";

export interface ReadinessCheck {
  key: string;
  ok: boolean;
  detail: string;
}

export interface PublishingReadiness {
  configured: boolean;
  readyForTest: boolean;
  publishingVerified: boolean;
  publishProvider: string;
  enableRealPublishing: boolean;
  livePublishRequireCanary: boolean;
  canaryPostIds: string[];
  linkedinApiVersion: string;
  personUrn: string | null;
  selectedPostId: string | null;
  selectedPostCanaryApproved: boolean | null;
  selectedPostStatus: string | null;
  pendingScheduledPosts: number;
  pendingScheduledNonCanary: number;
  checks: ReadinessCheck[];
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function parsePublishingReadiness(payload: unknown): PublishingReadiness {
  if (!isRecord(payload)) {
    throw new Error("Publishing readiness response was not an object.");
  }

  const checksRaw = payload.checks;
  const checks: ReadinessCheck[] = Array.isArray(checksRaw)
    ? checksRaw
        .filter(isRecord)
        .map((item) => ({
          key: typeof item.key === "string" ? item.key : "unknown",
          ok: Boolean(item.ok),
          detail: typeof item.detail === "string" ? item.detail : "",
        }))
    : [];

  const canaryIds = Array.isArray(payload.canary_post_ids)
    ? payload.canary_post_ids.filter((id): id is string => typeof id === "string")
    : [];

  return {
    configured: Boolean(payload.configured),
    readyForTest: Boolean(payload.ready_for_test),
    publishingVerified: Boolean(payload.publishing_verified),
    publishProvider: typeof payload.publish_provider === "string" ? payload.publish_provider : "unknown",
    enableRealPublishing: Boolean(payload.enable_real_publishing),
    livePublishRequireCanary: Boolean(payload.live_publish_require_canary),
    canaryPostIds: canaryIds,
    linkedinApiVersion:
      typeof payload.linkedin_api_version === "string" ? payload.linkedin_api_version : "",
    personUrn: optionalString(payload.person_urn),
    selectedPostId: optionalString(payload.selected_post_id),
    selectedPostCanaryApproved:
      typeof payload.selected_post_canary_approved === "boolean"
        ? payload.selected_post_canary_approved
        : null,
    selectedPostStatus: optionalString(payload.selected_post_status),
    pendingScheduledPosts:
      typeof payload.pending_scheduled_posts === "number" ? payload.pending_scheduled_posts : 0,
    pendingScheduledNonCanary:
      typeof payload.pending_scheduled_non_canary === "number"
        ? payload.pending_scheduled_non_canary
        : 0,
    checks,
  };
}

export async function getPublishingReadiness(
  postId?: string | null,
  signal?: AbortSignal,
): Promise<PublishingReadiness> {
  const query = postId ? `?post_id=${encodeURIComponent(postId)}` : "";
  return apiGet(`/api/v1/publishing/readiness${query}`, parsePublishingReadiness, {
    credentials: "include",
    signal,
  });
}
