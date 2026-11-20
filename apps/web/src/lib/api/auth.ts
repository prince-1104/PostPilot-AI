import { apiGet, apiPostEmpty, isRecord } from "@/lib/api/client";
import { env } from "@/lib/env";

export interface UserProfile {
  id: string;
  displayName: string;
  email: string | null;
  avatarUrl: string | null;
  linkedinSubject: string;
}

export function parseUserProfile(payload: unknown): UserProfile {
  if (!isRecord(payload)) {
    throw new Error("User profile response was not an object.");
  }
  const { id, display_name, email, avatar_url, linkedin_subject } = payload;
  if (
    typeof id !== "string" ||
    typeof display_name !== "string" ||
    typeof linkedin_subject !== "string"
  ) {
    throw new Error("User profile response was missing required fields.");
  }
  return {
    id,
    displayName: display_name,
    email: typeof email === "string" ? email : null,
    avatarUrl: typeof avatar_url === "string" ? avatar_url : null,
    linkedinSubject: linkedin_subject,
  };
}

export async function getMe(signal?: AbortSignal): Promise<UserProfile> {
  return apiGet("/api/v1/auth/me", parseUserProfile, {
    credentials: "include",
    signal,
  });
}

export async function logout(): Promise<void> {
  await apiPostEmpty("/api/v1/auth/logout", { credentials: "include" });
}

/** Absolute URL that starts the LinkedIn OAuth redirect from the API. */
export function linkedInAuthorizeUrl(): string {
  return `${env.apiBaseUrl}/api/v1/auth/linkedin`;
}
