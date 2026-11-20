import { env } from "@/lib/env";

export interface ApiErrorDetail {
  field: string | null;
  message: string;
  type: string;
}

/** The API answered with a non-2xx status and its standard error envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;
  readonly details: readonly ApiErrorDetail[];

  constructor(
    status: number,
    body: { code: string; message: string; requestId: string; details: ApiErrorDetail[] },
  ) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.requestId = body.requestId;
    this.details = body.details;
  }
}

/** The API answered, but not with a payload this client understands. */
export class UnexpectedResponseError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "UnexpectedResponseError";
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseErrorDetail(value: unknown): ApiErrorDetail | null {
  if (!isRecord(value)) return null;
  const { field, message, type } = value;
  if (typeof message !== "string" || typeof type !== "string") return null;
  return { field: typeof field === "string" ? field : null, message, type };
}

function toApiError(status: number, payload: unknown): ApiError | UnexpectedResponseError {
  const error = isRecord(payload) ? payload.error : undefined;
  if (
    !isRecord(error) ||
    typeof error.code !== "string" ||
    typeof error.message !== "string" ||
    typeof error.request_id !== "string"
  ) {
    return new UnexpectedResponseError(
      `The API returned HTTP ${status} without the expected error envelope.`,
    );
  }

  const details = Array.isArray(error.details)
    ? error.details.map(parseErrorDetail).filter((detail) => detail !== null)
    : [];

  return new ApiError(status, {
    code: error.code,
    message: error.message,
    requestId: error.request_id,
    details,
  });
}

interface RequestOptions {
  signal?: AbortSignal;
  /** When true, send cookies (session) cross-origin. Default false for public GETs. */
  credentials?: RequestCredentials;
}

async function parseJson(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }
  try {
    return await response.json();
  } catch (cause) {
    throw new UnexpectedResponseError(
      `The API returned HTTP ${response.status} with a body that is not valid JSON.`,
      { cause },
    );
  }
}

/**
 * Sends a GET request to the API and validates the response with `parse`.
 *
 * Rejects with `ApiError` for an error envelope, `UnexpectedResponseError` for a
 * payload that cannot be understood, and the underlying `fetch` error when the
 * request never completes (network failure, CORS rejection, or abort).
 */
export async function apiGet<T>(
  path: string,
  parse: (payload: unknown) => T,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    credentials: options.credentials ?? "omit",
    signal: options.signal ?? null,
  });

  const payload = await parseJson(response);
  if (!response.ok) {
    throw toApiError(response.status, payload);
  }
  return parse(payload);
}

export async function apiPost<T>(
  path: string,
  parse: (payload: unknown) => T,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    method: "POST",
    headers: { Accept: "application/json" },
    cache: "no-store",
    credentials: options.credentials ?? "include",
    signal: options.signal ?? null,
  });

  const payload = await parseJson(response);
  if (!response.ok) {
    throw toApiError(response.status, payload);
  }
  return parse(payload);
}

export async function apiPostEmpty(
  path: string,
  options: RequestOptions = {},
): Promise<void> {
  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    method: "POST",
    headers: { Accept: "application/json" },
    cache: "no-store",
    credentials: options.credentials ?? "include",
    signal: options.signal ?? null,
  });

  if (response.status === 204) {
    return;
  }

  const payload = await parseJson(response);
  if (!response.ok) {
    throw toApiError(response.status, payload);
  }
}
