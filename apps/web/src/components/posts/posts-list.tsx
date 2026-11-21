"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Plus, RefreshCw } from "lucide-react";

import { PostStatusBadge } from "@/components/posts/post-status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { PremiumCard } from "@/components/ui/premium-card";
import { Skeleton } from "@/components/ui/skeleton-loader";
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
  { value: "processing", label: "Processing" },
  { value: "published", label: "Published" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "requires_review", label: "Requires review" },
];

const POLL_MS = 5000;

function preview(content: string, max = 160): string {
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

    function load(signal: AbortSignal) {
      return listPosts({
        status: status || undefined,
        limit: 20,
        signal,
      })
        .then((page) => {
          if (signal.aborted) return;
          setItems(page.items);
          setNextCursor(page.nextCursor);
          setLoadState("ready");
          setError(null);
        })
        .catch((err: unknown) => {
          if (signal.aborted) return;
          if (err instanceof ApiError && err.status === 401) {
            setLoadState("signed_out");
            setItems([]);
            setNextCursor(null);
            return;
          }
          setLoadState("error");
          setError(err instanceof Error ? err.message : "Could not load posts.");
        });
    }

    void load(controller.signal);
    const timer = window.setInterval(() => {
      void load(controller.signal);
    }, POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
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
        "Cancel this scheduled post? It will not be published. This cannot be undone.",
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
      <EmptyState
        title="Sign in to manage posts"
        description="Connect LinkedIn on the Connections page before managing posts."
        action={<Button render={<Link href="/connections" />}>Go to Connections</Button>}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="flex flex-wrap gap-1.5 rounded-xl border border-border/80 bg-background-elevated/60 p-1"
          role="group"
          aria-label="Filter by status"
        >
          {STATUS_FILTERS.map((filter) => (
            <Button
              key={filter.value || "all"}
              type="button"
              size="sm"
              variant={status === filter.value ? "default" : "ghost"}
              className={
                status === filter.value
                  ? "bg-surface-active shadow-sm"
                  : "text-muted-foreground"
              }
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
            className="bg-surface/40"
            onClick={() => {
              setLoadState("loading");
              setReloadToken((value) => value + 1);
            }}
          >
            <RefreshCw data-icon="inline-start" />
            Refresh
          </Button>
          <Button
            render={<Link href="/posts/new" />}
            className="gradient-primary border-0 text-white"
          >
            <Plus data-icon="inline-start" />
            New post
          </Button>
        </div>
      </div>

      {error ? (
        <p className="rounded-xl border border-rose/30 bg-rose/10 px-4 py-3 text-sm text-rose" role="alert">
          {error}
        </p>
      ) : null}

      {loadState === "loading" ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((key) => (
            <div key={key} className="surface-panel space-y-3 rounded-2xl p-5">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      ) : null}

      {loadState === "ready" && items.length === 0 ? (
        <EmptyState
          icon={Plus}
          title="No posts yet"
          description="Schedule your first LinkedIn post or draft one with AI Studio."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button render={<Link href="/posts/new" />}>Schedule post</Button>
              <Button variant="outline" render={<Link href="/assistant" />}>
                Open AI Studio
              </Button>
            </div>
          }
        />
      ) : null}

      {items.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {items.map((post) => (
            <li key={post.id}>
              <PremiumCard interactive className="p-4 sm:p-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1 space-y-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <PostStatusBadge status={post.status} />
                      <span className="font-meta">
                        {formatInTimezone(post.scheduledAt, post.timezone)} · {post.timezone}
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                      {preview(post.content)}
                    </p>
                    {post.nextAttemptAt &&
                    (post.status === "scheduled" || post.status === "processing") ? (
                      <p className="font-meta">
                        Next retry: {formatInTimezone(post.nextAttemptAt, post.timezone)}
                      </p>
                    ) : null}
                    {post.status === "scheduled" ? (
                      <p className="text-xs text-muted-foreground">
                        {post.publishApproved
                          ? "Approved for LinkedIn publishing"
                          : "Not approved — will not publish until confirmed"}
                      </p>
                    ) : null}
                    {post.publicationSimulated ? (
                      <p className="text-xs text-muted-foreground">
                        Not a real LinkedIn post (test/simulation URN)
                      </p>
                    ) : null}
                    {post.status === "requires_review" ? (
                      <p className="text-xs text-amber">Requires review — will not auto-republish</p>
                    ) : null}
                    {post.connectionExpiryWarning ? (
                      <p className="text-xs text-amber">{post.connectionExpiryWarning}</p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <Button
                      render={<Link href={`/posts/${post.id}` as `/posts/${string}`} />}
                      variant="outline"
                      size="sm"
                      className="bg-surface/40"
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
                </div>
              </PremiumCard>
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
