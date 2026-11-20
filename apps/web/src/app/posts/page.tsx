import type { Metadata } from "next";
import { Suspense } from "react";

import { PostsList } from "@/components/posts/posts-list";

export const metadata: Metadata = {
  title: { absolute: "Posts · PostPilot AI" },
};

export default function PostsPage() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Posts</h1>
        <p className="max-w-2xl text-muted-foreground">
          Schedule LinkedIn posts for a future time. Publishing to LinkedIn happens in a later
          phase; here you create, edit, and cancel scheduled drafts.
        </p>
      </header>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading posts…</p>}>
        <PostsList />
      </Suspense>
    </div>
  );
}
