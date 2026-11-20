import { apiGet, isRecord, UnexpectedResponseError } from "@/lib/api/client";

export const READINESS_PATH = "/api/v1/health/ready";

/** Error code the API uses when a backing service, such as PostgreSQL, is down. */
export const DEPENDENCY_UNAVAILABLE = "dependency_unavailable";

export interface Readiness {
  status: "ready";
  checks: { database: "ok" };
}

function parseReadiness(payload: unknown): Readiness {
  if (
    isRecord(payload) &&
    payload.status === "ready" &&
    isRecord(payload.checks) &&
    payload.checks.database === "ok"
  ) {
    return { status: "ready", checks: { database: "ok" } };
  }
  throw new UnexpectedResponseError("The readiness response did not match the expected shape.");
}

/** Resolves when the API is up and can reach PostgreSQL. */
export function getReadiness(signal: AbortSignal): Promise<Readiness> {
  return apiGet(READINESS_PATH, parseReadiness, { signal });
}
