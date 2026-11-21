"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { ScheduleDateTimePicker } from "@/components/posts/schedule-datetime-picker";
import { EmptyState } from "@/components/ui/empty-state";
import { PremiumCard } from "@/components/ui/premium-card";
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
  "w-full rounded-xl border border-input bg-background-elevated/80 px-3 py-2.5 text-sm outline-none transition-shadow focus-visible:border-violet/50 focus-visible:ring-3 focus-visible:ring-violet/30";

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
  const [confirmOpen, setConfirmOpen] = useState(false);
  const idempotencyKeyRef = useRef("");

  useEffect(() => {
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

  const accountLabel = connection?.displayName ?? "Connected LinkedIn account";

  const canSchedule =
    loadState === "ready" &&
    connection?.connected === true &&
    Boolean(connection.id) &&
    connection.grantedScopes.includes("w_member_social") &&
    content.trim().length > 0 &&
    content.trim().length <= CONTENT_MAX &&
    Boolean(previewIso) &&
    !submitting;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSchedule) return;
    setError(null);
    setConfirmOpen(true);
  }

  async function confirmAndSchedule() {
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
          confirmPublish: true,
        },
        idempotencyKeyRef.current,
      );
      idempotencyKeyRef.current = newIdempotencyKey();
      setContent("");
      setLocalWhen(defaultLocalDateTime(timezone));
      setConfirmOpen(false);
      setSubmitting(false);
      router.push(`/posts/${post.id}?scheduled=1`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not schedule the post.");
      setSubmitting(false);
      setConfirmOpen(false);
    }
  }

  const scheduleBlockReason = (() => {
    if (submitting) return null;
    if (content.trim().length === 0) return "Enter post content to enable scheduling.";
    if (content.trim().length > CONTENT_MAX) return `Content must be at most ${CONTENT_MAX} characters.`;
    if (!previewIso) return "Pick a valid local date and time.";
    return null;
  })();

  if (loadState === "loading") {
    return <p className="text-sm text-muted-foreground">Loading connection…</p>;
  }

  if (loadState === "signed_out") {
    return (
      <EmptyState
        title="Sign in to schedule"
        description="Sign in with LinkedIn before scheduling a post."
        action={<Button render={<Link href="/connections" />}>Go to Connections</Button>}
      />
    );
  }

  if (!connection?.connected || !connection.id) {
    return (
      <EmptyState
        title="Connect LinkedIn first"
        description="A connected LinkedIn account with posting permission is required to schedule."
        action={<Button render={<Link href="/connections" />}>Manage connection</Button>}
      />
    );
  }

  if (!connection.grantedScopes.includes("w_member_social")) {
    return (
      <EmptyState
        title="Missing publishing permission"
        description="This connection is missing w_member_social. Reconnect on the Connections page."
        action={<Button render={<Link href="/connections" />}>Reconnect LinkedIn</Button>}
      />
    );
  }

  return (
    <>
      <form onSubmit={handleSubmit} className="grid gap-6 lg:grid-cols-5">
        <div className="flex flex-col gap-5 lg:col-span-3">
          <PremiumCard className="space-y-5">
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
                <option value={connection.id}>{accountLabel}</option>
              </select>
              <p id="linkedin-account-help" className="text-xs text-muted-foreground">
                Posts publish as this connected account.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-3">
                <label htmlFor="post-content" className="text-sm font-medium">
                  Post content
                </label>
                <span className="font-meta">
                  {content.trim().length} / {CONTENT_MAX}
                </span>
              </div>
              <textarea
                id="post-content"
                className={`${fieldClass} min-h-48 resize-y`}
                value={content}
                maxLength={CONTENT_MAX}
                required
                onChange={(event) => setContent(event.target.value)}
                placeholder="Share an update with your network…"
              />
            </div>

            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">When to publish</p>
              <ScheduleDateTimePicker
                value={localWhen}
                timeZone={timezone}
                onChange={setLocalWhen}
                disabled={submitting}
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

            {error ? (
              <p className="rounded-xl border border-rose/30 bg-rose/10 px-3 py-2 text-sm text-rose" role="alert">
                {error}
              </p>
            ) : null}

            {scheduleBlockReason ? (
              <p className="text-sm text-muted-foreground" role="status">
                {scheduleBlockReason}
              </p>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <Button
                type="submit"
                disabled={!canSchedule}
                className="gradient-primary border-0 text-white"
              >
                Schedule &amp; Publish
              </Button>
              <Button type="button" variant="outline" render={<Link href="/posts" />}>
                Cancel
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              You can schedule as many future posts as you need. Each submit creates a separate post.
            </p>
          </PremiumCard>
        </div>

        <div className="flex flex-col gap-4 lg:col-span-2">
          <PremiumCard glow="blue" className="space-y-4">
            <p className="font-mono text-[10px] tracking-[0.16em] text-electric-blue uppercase">
              Preview
            </p>
            <div className="rounded-2xl border border-border bg-background p-4">
              <div className="mb-3 flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-full bg-electric-blue/20 text-xs font-semibold text-electric-blue">
                  in
                </span>
                <div>
                  <p className="text-sm font-semibold">{accountLabel}</p>
                  <p className="font-meta">LinkedIn-style preview · not official UI</p>
                </div>
              </div>
              <p className="min-h-24 whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                {content.trim() || "Your post content will appear here."}
              </p>
            </div>
          </PremiumCard>

          <PremiumCard className="space-y-3">
            <p className="text-sm font-medium">Scheduling summary</p>
            {previewIso ? (
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">Local</dt>
                  <dd className="text-right font-medium">
                    {formatInTimezone(previewIso, timezone)}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">Timezone</dt>
                  <dd className="font-meta text-right">{timezone}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">UTC</dt>
                  <dd className="font-meta text-right">{new Date(previewIso).toISOString()}</dd>
                </div>
              </dl>
            ) : (
              <p className="text-sm text-rose">Enter a valid local date and time.</p>
            )}
            {connection.tokenExpiresAt ? (
              <p className="text-xs text-muted-foreground">
                Token expiry: {new Date(connection.tokenExpiresAt).toLocaleString()}
              </p>
            ) : null}
          </PremiumCard>
        </div>
      </form>

      {confirmOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="publish-confirm-title"
        >
          <div className="w-full max-w-md rounded-2xl border border-border bg-background-elevated p-6 shadow-2xl">
            <h2 id="publish-confirm-title" className="font-heading text-lg font-semibold">
              Confirm LinkedIn publication
            </h2>
            <p className="mt-3 text-sm text-muted-foreground">
              This post will automatically publish to{" "}
              <span className="font-medium text-foreground">{accountLabel}</span> on{" "}
              <span className="font-medium text-foreground">
                {previewIso ? formatInTimezone(previewIso, timezone) : "the selected time"}
              </span>
              .
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              Confirming stores publishing approval with your signed-in account.
            </p>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={submitting}
                onClick={() => setConfirmOpen(false)}
              >
                Go back
              </Button>
              <Button
                type="button"
                disabled={submitting}
                className="gradient-primary border-0 text-white"
                onClick={() => void confirmAndSchedule()}
              >
                {submitting ? "Scheduling…" : "Confirm & schedule"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
