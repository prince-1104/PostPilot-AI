"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PostStatusBadge } from "@/components/posts/post-status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  cancelPost,
  getPost,
  listPostAttempts,
  updatePost,
  type PublishAttempt,
  type ScheduledPost,
} from "@/lib/api/posts";
import {
  getPublishingReadiness,
  type PublishingReadiness,
} from "@/lib/api/publishing";

const POLL_MS = 4000;
import {
  formatInTimezone,
  instantToWallLocalInput,
  listIanaTimezones,
  wallTimeToOffsetAwareIso,
} from "@/lib/timezone";

const CONTENT_MAX = 3000;

const fieldClass =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

export function PostDetail({ postId }: { postId: string }) {
  const router = useRouter();
  const timezones = useMemo(() => listIanaTimezones(), []);

  const [post, setPost] = useState<ScheduledPost | null>(null);
  const [attempts, setAttempts] = useState<PublishAttempt[]>([]);
  const [readiness, setReadiness] = useState<PublishingReadiness | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "missing" | "error" | "signed_out">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [localWhen, setLocalWhen] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function refresh(signal: AbortSignal, initial: boolean) {
      try {
        const [data, history, publishing] = await Promise.all([
          getPost(postId, signal),
          listPostAttempts(postId, signal),
          getPublishingReadiness(postId, signal),
        ]);
        if (signal.aborted) return;
        setPost(data);
        setAttempts(history);
        setReadiness(publishing);
        if (initial || !editing) {
          setContent(data.content);
          setTimezone(data.timezone);
          setLocalWhen(instantToWallLocalInput(data.scheduledAt, data.timezone));
        }
        setLoadState("ready");
      } catch (err: unknown) {
        if (signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setLoadState("signed_out");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setLoadState("missing");
          return;
        }
        if (initial) {
          setLoadState("error");
          setError(err instanceof Error ? err.message : "Could not load post.");
        }
      }
    }

    void refresh(controller.signal, true);
    const timer = window.setInterval(() => {
      void refresh(controller.signal, false);
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [postId, editing]);

  async function handleSave() {
    if (!post) return;
    setBusy(true);
    setError(null);
    try {
      const scheduledAt = wallTimeToOffsetAwareIso(localWhen, timezone);
      const updated = await updatePost(post.id, {
        expectedVersion: post.version,
        content: content.trim(),
        scheduledAt,
        timezone,
      });
      setPost(updated);
      setContent(updated.content);
      setTimezone(updated.timezone);
      setLocalWhen(instantToWallLocalInput(updated.scheduledAt, updated.timezone));
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (!post) return;
    if (
      !window.confirm(
        "Cancel this scheduled post? It will not be published.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await cancelPost(post.id, post.version);
      setPost(updated);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed.");
    } finally {
      setBusy(false);
    }
  }

  if (loadState === "loading") {
    return <p className="text-sm text-muted-foreground">Loading post…</p>;
  }

  if (loadState === "signed_out") {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">Sign in to view this post.</p>
        <Button render={<Link href="/connections" />}>Go to Connections</Button>
      </div>
    );
  }

  if (loadState === "missing") {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">Post not found.</p>
        <Button render={<Link href="/posts" />}>Back to posts</Button>
      </div>
    );
  }

  if (loadState === "error" || !post) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {error ?? "Something went wrong."}
      </p>
    );
  }

  const canEdit = post.status === "scheduled";

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <PostStatusBadge status={post.status} />
        <span className="text-sm text-muted-foreground">Version {post.version}</span>
      </div>

      {post.connectionExpiryWarning ? (
        <p
          className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-100"
          role="status"
        >
          {post.connectionExpiryWarning}
        </p>
      ) : null}

      {post.status === "scheduled" && readiness ? (
        <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm">
          <p className="font-medium">Live LinkedIn approval</p>
          <p className="mt-1 font-mono text-xs break-all">Post ID: {post.id}</p>
          <p className="mt-2 text-muted-foreground">
            Provider: <span className="font-mono">{readiness.publishProvider}</span>
            {" · "}
            Real publishing: {readiness.enableRealPublishing ? "on" : "off"}
            {" · "}
            Canary approved for this post:{" "}
            {readiness.selectedPostCanaryApproved ? "yes" : "no"}
          </p>
          {!readiness.enableRealPublishing || readiness.publishProvider !== "linkedin" ? (
            <p className="mt-2 text-xs text-muted-foreground">
              To publish this post on your real LinkedIn profile, set{" "}
              <span className="font-mono">PUBLISH_PROVIDER=linkedin</span>,{" "}
              <span className="font-mono">ENABLE_REAL_PUBLISHING=true</span>, keep{" "}
              <span className="font-mono">LIVE_PUBLISH_REQUIRE_CANARY=true</span>, and set{" "}
              <span className="font-mono">LIVE_PUBLISH_CANARY_POST_IDS</span> to this UUID only.
              Then recreate api/worker/beat. See docs/live-e2e-publishing.md.
            </p>
          ) : readiness.selectedPostCanaryApproved ? (
            <p className="mt-2 text-xs text-emerald-800 dark:text-emerald-200">
              This post is on the live canary allowlist. When it becomes due, the worker will call
              LinkedIn&apos;s real Posts API (not the fake publisher).
            </p>
          ) : (
            <p className="mt-2 text-xs text-amber-800 dark:text-amber-200">
              Real publishing is enabled, but this UUID is not on{" "}
              <span className="font-mono">LIVE_PUBLISH_CANARY_POST_IDS</span>. It will not be
              sent to LinkedIn until you approve it explicitly.
            </p>
          )}
          {readiness.pendingScheduledNonCanary > 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              {readiness.pendingScheduledNonCanary} other scheduled post(s) remain blocked by the
              canary gate.
            </p>
          ) : null}
        </div>
      ) : null}

      {editing && canEdit ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-3">
              <label htmlFor="edit-content" className="text-sm font-medium">
                Content
              </label>
              <span className="text-xs text-muted-foreground">
                {content.trim().length} / {CONTENT_MAX}
              </span>
            </div>
            <textarea
              id="edit-content"
              className={`${fieldClass} min-h-40 resize-y`}
              value={content}
              maxLength={CONTENT_MAX}
              onChange={(event) => setContent(event.target.value)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <label htmlFor="edit-when" className="text-sm font-medium">
                Local date and time
              </label>
              <input
                id="edit-when"
                type="datetime-local"
                className={fieldClass}
                value={localWhen}
                onChange={(event) => setLocalWhen(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="edit-tz" className="text-sm font-medium">
                Timezone
              </label>
              <select
                id="edit-tz"
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
          <div className="flex flex-wrap gap-2">
            <Button type="button" disabled={busy} onClick={() => void handleSave()}>
              Save changes
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setContent(post.content);
                setTimezone(post.timezone);
                setLocalWhen(instantToWallLocalInput(post.scheduledAt, post.timezone));
                setEditing(false);
              }}
            >
              Discard
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div>
            <h2 className="text-sm font-medium text-muted-foreground">Content</h2>
            <p className="mt-1 whitespace-pre-wrap text-sm">{post.content}</p>
          </div>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Scheduled for</dt>
              <dd>
                {formatInTimezone(post.scheduledAt, post.timezone)} ({post.timezone})
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">UTC instant</dt>
              <dd className="font-mono text-xs">{post.scheduledAt}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Created</dt>
              <dd>{formatInTimezone(post.createdAt, post.timezone)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Updated</dt>
              <dd>{formatInTimezone(post.updatedAt, post.timezone)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Attempts</dt>
              <dd>{post.attemptCount}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Next retry</dt>
              <dd>
                {post.nextAttemptAt
                  ? formatInTimezone(post.nextAttemptAt, post.timezone)
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Published at</dt>
              <dd>
                {post.publishedAt ? formatInTimezone(post.publishedAt, post.timezone) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">LinkedIn post URN</dt>
              <dd className="font-mono text-xs">{post.linkedinPostUrn ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Last error</dt>
              <dd>{post.lastErrorCode ?? "—"}</dd>
            </div>
          </dl>
          {post.status === "published" && post.linkedinPermalink && !post.publicationSimulated ? (
            <p>
              <a
                href={post.linkedinPermalink}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-medium underline underline-offset-4"
              >
                Open on LinkedIn
              </a>
            </p>
          ) : null}
        </div>
      )}

      {post.status === "failed" ? (
        <div
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm"
          role="alert"
        >
          <p className="font-medium text-destructive">Publishing failed</p>
          <p className="mt-1 text-destructive/90">
            {post.lastErrorCode
              ? `Error code: ${post.lastErrorCode}.`
              : "No sanitized error code was recorded."}
          </p>
          {post.reconnectRequired ? (
            <p className="mt-2">
              Reconnect LinkedIn on the{" "}
              <Link href="/connections" className="underline underline-offset-4">
                Connections
              </Link>{" "}
              page, then schedule a new post. PostPilot does not refresh LinkedIn tokens.
            </p>
          ) : null}
          {attempts[0] ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Most recent attempt #{attempts[attempts.length - 1]?.attemptNumber}:{" "}
              {attempts[attempts.length - 1]?.sanitizedErrorCode ??
                attempts[attempts.length - 1]?.executionState}
            </p>
          ) : null}
        </div>
      ) : null}

      {post.status === "requires_review" ? (
        <p
          className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:text-amber-100"
          role="status"
        >
          This post needs manual review. The LinkedIn API call may already have created the post,
          so PostPilot will not automatically resubmit it. There is no one-click retry. Check the
          attempt history below and your LinkedIn profile before taking further action.
        </p>
      ) : null}

      {post.publicationSimulated ? (
        <p className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          This URN is from an isolated test/simulation run. It is <strong>not</strong> a real
          LinkedIn publication.
        </p>
      ) : null}

      {post.status === "published" && !post.publicationSimulated ? (
        <p className="text-sm text-muted-foreground">
          Confirmed LinkedIn publication
          {attempts.length > 0 && attempts[attempts.length - 1]?.providerHttpStatus
            ? ` (HTTP ${attempts[attempts.length - 1]?.providerHttpStatus})`
            : ""}
          .
        </p>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="font-heading text-lg font-medium">Publishing attempts</h2>
        {attempts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No publish attempts yet.</p>
        ) : (
          <ol className="divide-y divide-border rounded-lg border border-border">
            {attempts.map((attempt) => (
              <li key={attempt.id} className="space-y-1 px-4 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">Attempt {attempt.attemptNumber}</span>
                  <span className="text-muted-foreground">{attempt.executionState}</span>
                  {attempt.publicationSimulated ? (
                    <span className="text-xs text-muted-foreground">simulated</span>
                  ) : null}
                </div>
                <p className="text-xs text-muted-foreground">
                  Started {formatInTimezone(attempt.startedAt, post.timezone)}
                  {attempt.finishedAt
                    ? ` · Finished ${formatInTimezone(attempt.finishedAt, post.timezone)}`
                    : ""}
                </p>
                {attempt.providerHttpStatus != null ? (
                  <p className="text-xs">HTTP {attempt.providerHttpStatus}</p>
                ) : null}
                {attempt.sanitizedErrorCode ? (
                  <p className="text-xs">Error: {attempt.sanitizedErrorCode}</p>
                ) : null}
                {attempt.errorCategory ? (
                  <p className="text-xs text-muted-foreground">
                    Category: {attempt.errorCategory}
                  </p>
                ) : null}
                {attempt.nextRetryAt ? (
                  <p className="text-xs">
                    Retry at {formatInTimezone(attempt.nextRetryAt, post.timezone)}
                  </p>
                ) : null}
                {attempt.providerPostUrn ? (
                  <p className="font-mono text-xs">{attempt.providerPostUrn}</p>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {canEdit && !editing ? (
          <Button type="button" disabled={busy} onClick={() => setEditing(true)}>
            Edit / reschedule
          </Button>
        ) : null}
        {canEdit ? (
          <Button type="button" variant="destructive" disabled={busy} onClick={() => void handleCancel()}>
            Cancel post
          </Button>
        ) : null}
        <Button type="button" variant="outline" render={<Link href="/posts" />}>
          Back to list
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => router.refresh()}
        >
          Refresh
        </Button>
      </div>
    </div>
  );
}
