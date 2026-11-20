import type { Metadata } from "next";
import { Suspense } from "react";

import { PostDetail } from "@/components/posts/post-detail";

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
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Post details</h1>
        <p className="max-w-2xl text-muted-foreground">
          Review status, edit or reschedule while the post is still scheduled, or cancel it.
        </p>
      </header>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading post…</p>}>
        <PostDetailBody params={params} />
      </Suspense>
    </div>
  );
}
