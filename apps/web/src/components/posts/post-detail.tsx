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
  updatePost,
  type ScheduledPost,
} from "@/lib/api/posts";
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
    void getPost(postId, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setPost(data);
        setContent(data.content);
        setTimezone(data.timezone);
        setLocalWhen(instantToWallLocalInput(data.scheduledAt, data.timezone));
        setLoadState("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setLoadState("signed_out");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setLoadState("missing");
          return;
        }
        setLoadState("error");
        setError(err instanceof Error ? err.message : "Could not load post.");
      });
    return () => controller.abort();
  }, [postId]);

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
          </dl>
        </div>
      )}

      <div className="rounded-lg border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
        Publication history and LinkedIn delivery details are not available until Phase 4
        (background publishing). This phase only creates, edits, and cancels scheduled posts.
      </div>

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
