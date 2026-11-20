"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Plus } from "lucide-react";

import { PostStatusBadge } from "@/components/posts/post-status-badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  cancelPost,
  listPosts,
  type PostStatus,
  type ScheduledPost,
} from "@/lib/api/posts";
import { formatInTimezone } from "@/lib/timezone";

const STATUS_FILTERS: Array<{ value: "" | PostStatus; label: string }> = [
  { value: "", label: "All" },
  { value: "scheduled", label: "Scheduled" },
  { value: "cancelled", label: "Cancelled" },
  { value: "processing", label: "Processing" },
  { value: "published", label: "Published" },
  { value: "failed", label: "Failed" },
];

function preview(content: string, max = 140): string {
  const trimmed = content.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

export function PostsList() {
  const [status, setStatus] = useState<"" | PostStatus>("");
  const [items, setItems] = useState<ScheduledPost[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error" | "signed_out">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void listPosts({
      status: status || undefined,
      limit: 20,
      signal: controller.signal,
    })
      .then((page) => {
        if (controller.signal.aborted) return;
        setItems(page.items);
        setNextCursor(page.nextCursor);
        setLoadState("ready");
        setError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setLoadState("signed_out");
          setItems([]);
          setNextCursor(null);
          return;
        }
        setLoadState("error");
        setError(err instanceof Error ? err.message : "Could not load posts.");
      });
    return () => controller.abort();
  }, [status, reloadToken]);

  async function handleLoadMore() {
    if (!nextCursor) return;
    try {
      const page = await listPosts({
        status: status || undefined,
        cursor: nextCursor,
        limit: 20,
      });
      setItems((current) => [...current, ...page.items]);
      setNextCursor(page.nextCursor);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load more posts.");
    }
  }

  async function handleCancel(post: ScheduledPost) {
    if (
      !window.confirm(
        "Cancel this scheduled post? It will not be published. This cannot be undone from this phase.",
      )
    ) {
      return;
    }
    setBusyId(post.id);
    try {
      const updated = await cancelPost(post.id, post.version);
      setItems((current) => current.map((item) => (item.id === post.id ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed.");
    } finally {
      setBusyId(null);
    }
  }

  function changeStatus(next: "" | PostStatus) {
    setStatus(next);
    setLoadState("loading");
    setItems([]);
    setNextCursor(null);
    setError(null);
  }

  if (loadState === "signed_out") {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border p-6">
        <p className="text-sm text-muted-foreground">
          Sign in with LinkedIn on the Connections page before managing posts.
        </p>
        <Button render={<Link href="/connections" />}>Go to Connections</Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
          {STATUS_FILTERS.map((filter) => (
            <Button
              key={filter.value || "all"}
              type="button"
              size="sm"
              variant={status === filter.value ? "default" : "outline"}
              onClick={() => changeStatus(filter.value)}
            >
              {filter.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setLoadState("loading");
              setReloadToken((value) => value + 1);
            }}
          >
            Refresh
          </Button>
          <Button render={<Link href="/posts/new" />}>
            <Plus data-icon="inline-start" />
            New post
          </Button>
        </div>
      </div>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      {loadState === "loading" ? (
        <p className="text-sm text-muted-foreground">Loading posts…</p>
      ) : null}

      {loadState === "ready" && items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm text-muted-foreground">
            No posts yet. Schedule your first LinkedIn post to see it here.
          </p>
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {items.map((post) => (
            <li
              key={post.id}
              className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between"
            >
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <PostStatusBadge status={post.status} />
                  <span className="text-sm text-muted-foreground">
                    {formatInTimezone(post.scheduledAt, post.timezone)}
                    <span className="ml-1 text-xs">({post.timezone})</span>
                  </span>
                </div>
                <p className="whitespace-pre-wrap text-sm text-foreground">{preview(post.content)}</p>
                {post.connectionExpiryWarning ? (
                  <p className="text-xs text-amber-700 dark:text-amber-400">
                    {post.connectionExpiryWarning}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                <Button
                  render={<Link href={`/posts/${post.id}` as `/posts/${string}`} />}
                  variant="outline"
                  size="sm"
                >
                  Open
                </Button>
                {post.status === "scheduled" ? (
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={busyId === post.id}
                    onClick={() => void handleCancel(post)}
                  >
                    Cancel
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {nextCursor ? (
        <div>
          <Button type="button" variant="outline" onClick={() => void handleLoadMore()}>
            Load more
          </Button>
        </div>
      ) : null}
    </div>
  );
}
