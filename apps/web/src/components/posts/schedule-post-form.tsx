"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { getLinkedInConnection, type LinkedInConnection } from "@/lib/api/connections";
import { createPost, newIdempotencyKey } from "@/lib/api/posts";
import {
  defaultLocalDateTime,
  formatInTimezone,
  guessBrowserTimezone,
  listIanaTimezones,
  wallTimeToOffsetAwareIso,
} from "@/lib/timezone";

const CONTENT_MAX = 3000;

const fieldClass =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

export function SchedulePostForm() {
  const router = useRouter();
  const timezones = useMemo(() => listIanaTimezones(), []);
  const [timezone, setTimezone] = useState("UTC");
  const [localWhen, setLocalWhen] = useState("");
  const [content, setContent] = useState("");
  const [connection, setConnection] = useState<LinkedInConnection | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "signed_out" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const idempotencyKeyRef = useRef("");

  useEffect(() => {
    // Defer past prerender: Date.now / Intl timezone must run on the client only.
    const timer = window.setTimeout(() => {
      const zone = guessBrowserTimezone();
      setTimezone(zone);
      setLocalWhen(defaultLocalDateTime(zone));
      idempotencyKeyRef.current = newIdempotencyKey();
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void getLinkedInConnection(controller.signal)
      .then((status) => {
        if (controller.signal.aborted) return;
        setConnection(status);
        setLoadState("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setLoadState("signed_out");
          return;
        }
        setLoadState("error");
        setError(err instanceof Error ? err.message : "Could not load LinkedIn connection.");
      });
    return () => controller.abort();
  }, []);

  const previewIso = useMemo(() => {
    try {
      if (!localWhen) return null;
      return wallTimeToOffsetAwareIso(localWhen, timezone);
    } catch {
      return null;
    }
  }, [localWhen, timezone]);

  const canSchedule =
    loadState === "ready" &&
    connection?.connected === true &&
    Boolean(connection.id) &&
    connection.grantedScopes.includes("w_member_social") &&
    content.trim().length > 0 &&
    content.trim().length <= CONTENT_MAX &&
    Boolean(previewIso) &&
    !submitting;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!connection?.id || !previewIso || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const post = await createPost(
        {
          content: content.trim(),
          scheduledAt: previewIso,
          timezone,
          linkedinConnectionId: connection.id,
        },
        idempotencyKeyRef.current,
      );
      idempotencyKeyRef.current = newIdempotencyKey();
      router.push(`/posts/${post.id}`);
    } catch (err) {
      // Keep the same idempotency key so a network retry does not create duplicates.
      setError(err instanceof Error ? err.message : "Could not schedule the post.");
      setSubmitting(false);
    }
  }

  if (loadState === "loading") {
    return <p className="text-sm text-muted-foreground">Loading connection…</p>;
  }

  if (loadState === "signed_out") {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Sign in with LinkedIn before scheduling a post.
        </p>
        <Button render={<Link href="/connections" />}>Go to Connections</Button>
      </div>
    );
  }

  if (!connection?.connected || !connection.id) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border p-6">
        <p className="text-sm text-muted-foreground">
          A connected LinkedIn account with posting permission is required to schedule.
        </p>
        <Button render={<Link href="/connections" />}>Manage connection</Button>
      </div>
    );
  }

  if (!connection.grantedScopes.includes("w_member_social")) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border p-6">
        <p className="text-sm text-muted-foreground">
          This LinkedIn connection is missing the <code>w_member_social</code> permission.
          Reconnect on the Connections page.
        </p>
        <Button render={<Link href="/connections" />}>Reconnect LinkedIn</Button>
      </div>
    );
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <label htmlFor="linkedin-account" className="text-sm font-medium">
          LinkedIn account
        </label>
        <select
          id="linkedin-account"
          className={fieldClass}
          value={connection.id}
          disabled
          aria-describedby="linkedin-account-help"
        >
          <option value={connection.id}>
            {connection.displayName ?? "Connected LinkedIn account"}
          </option>
        </select>
        <p id="linkedin-account-help" className="text-xs text-muted-foreground">
          Posts publish as this connected account. Multiple LinkedIn accounts are not supported yet.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-3">
          <label htmlFor="post-content" className="text-sm font-medium">
            Post content
          </label>
          <span className="text-xs text-muted-foreground">
            {content.trim().length} / {CONTENT_MAX}
          </span>
        </div>
        <textarea
          id="post-content"
          className={`${fieldClass} min-h-40 resize-y`}
          value={content}
          maxLength={CONTENT_MAX}
          required
          onChange={(event) => setContent(event.target.value)}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label htmlFor="local-when" className="text-sm font-medium">
            Local date and time
          </label>
          <input
            id="local-when"
            type="datetime-local"
            className={fieldClass}
            value={localWhen}
            required
            onChange={(event) => setLocalWhen(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="timezone" className="text-sm font-medium">
            Timezone (IANA)
          </label>
          <select
            id="timezone"
            className={fieldClass}
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
          >
            {timezones.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm">
        <p className="font-medium">Scheduled instant</p>
        {previewIso ? (
          <p className="mt-1 text-muted-foreground">
            {formatInTimezone(previewIso, timezone)} ({timezone})
            <br />
            <span className="font-mono text-xs">{previewIso}</span>
          </p>
        ) : (
          <p className="mt-1 text-destructive">Enter a valid local date and time.</p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          The API stores UTC and keeps your IANA timezone for display. Naive local times are not
          accepted.
        </p>
      </div>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!canSchedule}>
          {submitting ? "Scheduling…" : "Schedule post"}
        </Button>
        <Button type="button" variant="outline" render={<Link href="/posts" />}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
