import { apiGet, apiPost, isRecord } from "@/lib/api/client";

export interface LinkedInConnection {
  connected: boolean;
  connectionStatus: string;
  displayName: string | null;
  avatarUrl: string | null;
  grantedScopes: string[];
  tokenExpiresAt: string | null;
  reauthorizationRequired: boolean;
  disconnectIsLocalOnly: boolean;
}

export function parseLinkedInConnection(payload: unknown): LinkedInConnection {
  if (!isRecord(payload)) {
    throw new Error("LinkedIn connection response was not an object.");
  }
  const {
    connected,
    connection_status,
    display_name,
    avatar_url,
    granted_scopes,
    token_expires_at,
    reauthorization_required,
    disconnect_is_local_only,
  } = payload;

  if (typeof connected !== "boolean" || typeof connection_status !== "string") {
    throw new Error("LinkedIn connection response was missing required fields.");
  }

  return {
    connected,
    connectionStatus: connection_status,
    displayName: typeof display_name === "string" ? display_name : null,
    avatarUrl: typeof avatar_url === "string" ? avatar_url : null,
    grantedScopes: Array.isArray(granted_scopes)
      ? granted_scopes.filter((scope): scope is string => typeof scope === "string")
      : [],
    tokenExpiresAt: typeof token_expires_at === "string" ? token_expires_at : null,
    reauthorizationRequired: Boolean(reauthorization_required),
    disconnectIsLocalOnly:
      typeof disconnect_is_local_only === "boolean" ? disconnect_is_local_only : true,
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
