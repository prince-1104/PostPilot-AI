import type { Metadata } from "next";
import { Suspense } from "react";

import { PostsList } from "@/components/posts/posts-list";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton-loader";

export const metadata: Metadata = {
  title: { absolute: "Posts · PostPilot AI" },
};

export default function PostsPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Publishing"
        title="Posts"
        description="Manage scheduled, published, and failed LinkedIn posts. Approve before publish — Celery handles delivery when enabled."
      />
      <Suspense
        fallback={
          <div className="space-y-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-28 w-full" />
          </div>
        }
      >
        <PostsList />
      </Suspense>
    </div>
  );
}
