import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SchedulePostForm } from "@/components/posts/schedule-post-form";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton-loader";

export const metadata: Metadata = {
  title: { absolute: "Schedule · PostPilot AI" },
};

export default function NewPostPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Publishing"
        title="Schedule a post"
        description="Compose content, pick a local time and IANA timezone, then confirm. Offset-aware timestamps keep daylight-saving transitions correct."
        actions={
          <Button render={<Link href="/posts" />} variant="outline" size="sm">
            ← Back to posts
          </Button>
        }
      />
      <Suspense fallback={<Skeleton className="h-64 w-full rounded-2xl" />}>
        <SchedulePostForm />
      </Suspense>
    </div>
  );
}
