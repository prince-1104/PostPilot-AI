/**
 * Public runtime configuration.
 *
 * `NEXT_PUBLIC_*` variables are inlined into the bundle when `next build` runs, so
 * each one must be referenced as a literal `process.env.NAME` expression.
 */

function parseApiBaseUrl(value: string | undefined): string {
  if (!value) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL is not set. Copy apps/web/.env.example to " +
        "apps/web/.env.local, or pass it as a build argument when building the image.",
    );
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL is not a valid URL: "${value}". ` +
        'Expected an absolute URL such as "http://localhost:8000".',
    );
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL must use http or https, received "${url.protocol}".`,
    );
  }

  return value.replace(/\/+$/, "");
}

export const env = {
  /** Origin of the PostPilot API, without a trailing slash. */
  apiBaseUrl: parseApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL),
} as const;
