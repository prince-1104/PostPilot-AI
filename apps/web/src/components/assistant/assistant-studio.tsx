"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { MessageSquarePlus, Sparkles } from "lucide-react";
import { cn } from "cn";

import { AssistantWidget } from "@/components/assistant/assistant-widget";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton-loader";
import { ApiError } from "@/lib/api/client";
import {
  createAssistantThread,
  listAssistantThreads,
  type AssistantThreadSummary,
} from "@/lib/api/assistant";

export function AssistantStudio() {
  const [threads, setThreads] = useState<AssistantThreadSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "signed_out" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void listAssistantThreads(controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        setThreads(items);
        setSelectedId((current) => current ?? items[0]?.id ?? null);
        setLoadState("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setLoadState("signed_out");
          return;
        }
        setLoadState("error");
        setError(err instanceof Error ? err.message : "Could not load conversations.");
      });
    return () => controller.abort();
  }, [refreshToken]);

  async function handleNew() {
    try {
      const thread = await createAssistantThread({});
      setThreads((current) => [
        {
          id: thread.id,
          status: thread.status,
          title: thread.title,
          createdAt: thread.createdAt,
          updatedAt: thread.updatedAt,
          responseState: thread.responseState,
          currentStage: thread.currentStage,
        },
        ...current,
      ]);
      setSelectedId(thread.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start a conversation.");
    }
  }

  if (loadState === "signed_out") {
    return (
      <EmptyState
        icon={Sparkles}
        title="Sign in to open AI Studio"
        description="Connect LinkedIn to draft, refine, and approve schedules with the assistant."
        action={
          <Button render={<Link href="/connections" />}>Go to Connections</Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="AI Workspace"
        title="AI Studio"
        description="Turn ideas into LinkedIn drafts with review, tone control, and explicit Approve & Schedule — never auto-publish."
        actions={
          <Button type="button" variant="outline" onClick={() => void handleNew()}>
            <MessageSquarePlus data-icon="inline-start" />
            New conversation
          </Button>
        }
      />

      {error ? (
        <p className="rounded-xl border border-rose/30 bg-rose/10 px-4 py-3 text-sm text-rose" role="alert">
          {error}
        </p>
      ) : null}

      <div className="grid min-h-[70vh] gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="surface-panel flex flex-col overflow-hidden rounded-2xl">
          <div className="flex items-center justify-between border-b border-border/70 px-3 py-2.5">
            <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
              Conversations
            </p>
            <Button
              type="button"
              size="icon-xs"
              variant="ghost"
              aria-label="Refresh conversations"
              onClick={() => setRefreshToken((value) => value + 1)}
            >
              <Sparkles className="size-3.5" />
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loadState === "loading" ? (
              <div className="space-y-2 p-1">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : null}
            {loadState === "ready" && threads.length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                No conversations yet. Start one to draft a post.
              </p>
            ) : null}
            <ul className="flex flex-col gap-1">
              {threads.map((thread) => {
                const active = thread.id === selectedId;
                return (
                  <li key={thread.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(thread.id)}
                      className={cn(
                        "w-full rounded-xl px-3 py-2.5 text-left transition-colors",
                        active
                          ? "bg-surface-active text-foreground"
                          : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
                      )}
                    >
                      <p className="truncate text-sm font-medium">
                        {thread.title?.trim() || "Untitled draft"}
                      </p>
                      <p className="font-meta mt-0.5 truncate">
                        {thread.currentStage?.replaceAll("_", " ") ?? thread.status}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </aside>

        <div className="min-h-[70vh]">
          <AssistantWidget
            variant="studio"
            threadIdOverride={selectedId}
            className="h-full"
          />
        </div>
      </div>
    </div>
  );
}
