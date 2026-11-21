"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Plus,
  Sparkles,
  XCircle,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import { EmptyState } from "@/components/ui/empty-state";
import { MetricCard } from "@/components/ui/metric-card";
import { PremiumCard } from "@/components/ui/premium-card";
import { PostStatusBadge } from "@/components/posts/post-status-badge";
import { Button } from "@/components/ui/button";
import { SkeletonCard } from "@/components/ui/skeleton-loader";
import { ApiError } from "@/lib/api/client";
import { listPosts, type ScheduledPost } from "@/lib/api/posts";
import { formatInTimezone } from "@/lib/timezone";

interface MetricBucket {
  scheduled: number | null;
  published: number | null;
  failed: number | null;
  requiresReview: number | null;
  scheduledCapped: boolean;
  publishedCapped: boolean;
  failedCapped: boolean;
  reviewCapped: boolean;
}

function preview(content: string, max = 120): string {
  const trimmed = content.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

function formatCount(value: number | null, capped: boolean): string {
  if (value == null) return "—";
  return capped ? `${value}+` : String(value);
}

export function CommandCenter() {
  const reduceMotion = useReducedMotion();
  const [metrics, setMetrics] = useState<MetricBucket>({
    scheduled: null,
    published: null,
    failed: null,
    requiresReview: null,
    scheduledCapped: false,
    publishedCapped: false,
    failedCapped: false,
    reviewCapped: false,
  });
  const [upcoming, setUpcoming] = useState<ScheduledPost[]>([]);
  const [recent, setRecent] = useState<ScheduledPost[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "signed_out" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;

    async function load() {
      try {
        const [scheduled, published, failed, review, allRecent] = await Promise.all([
          listPosts({ status: "scheduled", limit: 50, signal }),
          listPosts({ status: "published", limit: 50, signal }),
          listPosts({ status: "failed", limit: 50, signal }),
          listPosts({ status: "requires_review", limit: 50, signal }),
          listPosts({ limit: 8, signal }),
        ]);

        if (signal.aborted) return;

        const upcomingSorted = [...scheduled.items].sort(
          (a, b) => new Date(a.scheduledAt).getTime() - new Date(b.scheduledAt).getTime(),
        );

        setMetrics({
          scheduled: scheduled.items.length,
          published: published.items.length,
          failed: failed.items.length,
          requiresReview: review.items.length,
          scheduledCapped: Boolean(scheduled.nextCursor),
          publishedCapped: Boolean(published.nextCursor),
          failedCapped: Boolean(failed.nextCursor),
          reviewCapped: Boolean(review.nextCursor),
        });
        setUpcoming(upcomingSorted.slice(0, 5));
        setRecent(allRecent.items);
        setLoadState("ready");
        setError(null);
      } catch (err) {
        if (signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setLoadState("signed_out");
          return;
        }
        setLoadState("error");
        setError(err instanceof Error ? err.message : "Could not load dashboard.");
      }
    }

    void load();
    return () => controller.abort();
  }, []);

  return (
    <div className="flex flex-col gap-8">
      <motion.section
        initial={reduceMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.28 }}
        className="relative overflow-hidden rounded-3xl border border-border/80 bg-background-elevated/80 p-6 sm:p-8"
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-90"
          aria-hidden
          style={{
            background:
              "radial-gradient(ellipse 70% 80% at 0% 0%, rgb(139 92 246 / 0.28), transparent 55%), radial-gradient(ellipse 50% 60% at 100% 20%, rgb(59 130 246 / 0.2), transparent 50%), radial-gradient(ellipse 40% 50% at 70% 100%, rgb(34 211 238 / 0.1), transparent 45%)",
          }}
        />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-xl space-y-3">
            <p className="font-mono text-[11px] font-medium tracking-[0.18em] text-violet-light uppercase">
              PostPilot AI
            </p>
            <h1 className="font-heading text-[1.85rem] leading-tight font-semibold tracking-tight sm:text-[2.15rem]">
              Your content command center
            </h1>
            <p className="text-[0.95rem] leading-relaxed text-muted-foreground">
              Create smarter. Schedule effortlessly. Publish confidently.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              render={<Link href="/assistant" />}
              className="gradient-ai border-0 text-white shadow-[0_0_28px_-8px_rgb(168_85_247_/_0.55)]"
            >
              <Sparkles data-icon="inline-start" />
              Create with AI
            </Button>
            <Button variant="outline" render={<Link href="/posts/new" />} className="bg-surface/50">
              <Plus data-icon="inline-start" />
              Schedule Post
            </Button>
          </div>
        </div>
      </motion.section>

      {loadState === "signed_out" ? (
        <EmptyState
          icon={CalendarClock}
          title="Sign in to see your publishing command center"
          description="Connect LinkedIn to view scheduled posts, metrics, and recent activity."
          action={
            <Button render={<Link href="/connections" />}>Go to Connections</Button>
          }
        />
      ) : null}

      {loadState === "error" && error ? (
        <p className="rounded-xl border border-rose/30 bg-rose/10 px-4 py-3 text-sm text-rose" role="alert">
          {error}
        </p>
      ) : null}

      {loadState === "loading" ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : null}

      {loadState === "ready" ? (
        <>
          <section aria-label="Publishing metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Scheduled"
              value={formatCount(metrics.scheduled, metrics.scheduledCapped)}
              icon={CalendarClock}
              accent="blue"
              hint={metrics.scheduledCapped ? "Showing first 50+" : undefined}
            />
            <MetricCard
              label="Published"
              value={formatCount(metrics.published, metrics.publishedCapped)}
              icon={CheckCircle2}
              accent="emerald"
              hint={metrics.publishedCapped ? "Showing first 50+" : undefined}
            />
            <MetricCard
              label="Failed"
              value={formatCount(metrics.failed, metrics.failedCapped)}
              icon={XCircle}
              accent="rose"
              hint={metrics.failedCapped ? "Showing first 50+" : undefined}
            />
            <MetricCard
              label="Requires review"
              value={formatCount(metrics.requiresReview, metrics.reviewCapped)}
              icon={AlertTriangle}
              accent="amber"
              hint={metrics.reviewCapped ? "Showing first 50+" : undefined}
            />
          </section>

          <div className="grid gap-6 lg:grid-cols-5">
            <section className="lg:col-span-3" aria-labelledby="upcoming-heading">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 id="upcoming-heading" className="font-heading text-lg font-medium">
                  Upcoming posts
                </h2>
                <Button size="sm" variant="ghost" render={<Link href="/posts?status=scheduled" />}>
                  View all
                </Button>
              </div>
              {upcoming.length === 0 ? (
                <EmptyState
                  icon={CalendarClock}
                  title="No posts scheduled yet"
                  description="Schedule your first LinkedIn post or draft one with AI."
                  action={
                    <Button render={<Link href="/posts/new" />}>
                      <Plus data-icon="inline-start" />
                      Schedule Post
                    </Button>
                  }
                />
              ) : (
                <ul className="flex flex-col gap-3">
                  {upcoming.map((post) => (
                    <li key={post.id}>
                      <PremiumCard interactive className="p-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0 space-y-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <PostStatusBadge status={post.status} />
                              <span className="font-meta">
                                {formatInTimezone(post.scheduledAt, post.timezone)} ·{" "}
                                {post.timezone}
                              </span>
                            </div>
                            <p className="text-sm leading-relaxed text-foreground/90">
                              {preview(post.content)}
                            </p>
                          </div>
                          <Button
                            size="sm"
                            variant="outline"
                            render={<Link href={`/posts/${post.id}` as `/posts/${string}`} />}
                          >
                            Open
                          </Button>
                        </div>
                      </PremiumCard>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="flex flex-col gap-6 lg:col-span-2">
              <PremiumCard glow="violet" className="overflow-hidden p-0">
                <div className="gradient-ai h-1 w-full" aria-hidden />
                <div className="space-y-3 p-5">
                  <div className="flex size-10 items-center justify-center rounded-xl bg-violet/15 text-violet-light">
                    <Sparkles className="size-5" aria-hidden />
                  </div>
                  <h2 className="font-heading text-lg font-medium">Turn ideas into LinkedIn content</h2>
                  <p className="text-sm text-muted-foreground">
                    Open AI Studio to draft, refine tone, review warnings, and approve a schedule —
                    never auto-publish.
                  </p>
                  <Button render={<Link href="/assistant" />} className="gradient-primary border-0 text-white">
                    Launch AI Studio
                  </Button>
                </div>
              </PremiumCard>

              <div>
                <h2 className="mb-3 font-heading text-lg font-medium">Recent activity</h2>
                {recent.length === 0 ? (
                  <EmptyState
                    title="No post activity yet"
                    description="Scheduled and published posts will appear here."
                  />
                ) : (
                  <ul className="surface-panel divide-y divide-border/80 overflow-hidden rounded-2xl">
                    {recent.map((post) => (
                      <li key={post.id}>
                        <Link
                          href={`/posts/${post.id}` as `/posts/${string}`}
                          className="flex flex-col gap-1.5 px-4 py-3 transition-colors hover:bg-surface-hover/50"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <PostStatusBadge status={post.status} />
                            <span className="font-meta">
                              {formatInTimezone(post.scheduledAt, post.timezone)}
                            </span>
                          </div>
                          <p className="line-clamp-2 text-sm text-muted-foreground">
                            {preview(post.content, 90)}
                          </p>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
