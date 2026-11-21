import type { Metadata } from "next";
import { Suspense } from "react";

import { PostDetail } from "@/components/posts/post-detail";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton-loader";

export const metadata: Metadata = {
  title: { absolute: "Post · PostPilot AI" },
};

async function PostDetailBody({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PostDetail postId={id} />;
}

export default function PostDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Publishing"
        title="Post details"
        description="Review status, edit or reschedule while the post is still scheduled, or cancel it."
      />
      <Suspense fallback={<Skeleton className="h-48 w-full rounded-2xl" />}>
        <PostDetailBody params={params} />
      </Suspense>
    </div>
  );
}
