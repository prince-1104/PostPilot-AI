import { apiGet, apiPost, isRecord } from "@/lib/api/client";

export interface LinkedInConnection {
  connected: boolean;
  connectionStatus: string;
  id: string | null;
  displayName: string | null;
  avatarUrl: string | null;
  grantedScopes: string[];
  tokenExpiresAt: string | null;
  reauthorizationRequired: boolean;
  disconnectIsLocalOnly: boolean;
  hasPublishingPermission: boolean;
  tokenUnexpired: boolean;
  readyToSchedule: boolean;
  /** True only after a real LinkedIn post URN was persisted — not merely OAuth success. */
  publishingVerified: boolean;
  personUrn: string | null;
}

export function parseLinkedInConnection(payload: unknown): LinkedInConnection {
  if (!isRecord(payload)) {
    throw new Error("LinkedIn connection response was not an object.");
  }
  const {
    connected,
    connection_status,
    id,
    display_name,
    avatar_url,
    granted_scopes,
    token_expires_at,
    reauthorization_required,
    disconnect_is_local_only,
    has_publishing_permission,
    token_unexpired,
    ready_to_schedule,
    publishing_verified,
    person_urn,
  } = payload;

  if (typeof connected !== "boolean" || typeof connection_status !== "string") {
    throw new Error("LinkedIn connection response was missing required fields.");
  }

  return {
    connected,
    connectionStatus: connection_status,
    id: typeof id === "string" ? id : null,
    displayName: typeof display_name === "string" ? display_name : null,
    avatarUrl: typeof avatar_url === "string" ? avatar_url : null,
    grantedScopes: Array.isArray(granted_scopes)
      ? granted_scopes.filter((scope): scope is string => typeof scope === "string")
      : [],
    tokenExpiresAt: typeof token_expires_at === "string" ? token_expires_at : null,
    reauthorizationRequired: Boolean(reauthorization_required),
    disconnectIsLocalOnly:
      typeof disconnect_is_local_only === "boolean" ? disconnect_is_local_only : true,
    hasPublishingPermission: Boolean(has_publishing_permission),
    tokenUnexpired: Boolean(token_unexpired),
    readyToSchedule: Boolean(ready_to_schedule),
    publishingVerified: Boolean(publishing_verified),
    personUrn: typeof person_urn === "string" ? person_urn : null,
  };
}

export async function getLinkedInConnection(signal?: AbortSignal): Promise<LinkedInConnection> {
  return apiGet("/api/v1/connections/linkedin", parseLinkedInConnection, {
    credentials: "include",
    signal,
  });
}

export async function disconnectLinkedIn(): Promise<LinkedInConnection> {
  return apiPost("/api/v1/connections/linkedin/disconnect", parseLinkedInConnection, {
    credentials: "include",
  });
}
