import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SchedulePostForm } from "@/components/posts/schedule-post-form";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: { absolute: "New post · PostPilot AI" },
};

export default function NewPostPage() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <div>
          <Button render={<Link href="/posts" />} variant="ghost" size="sm">
            ← Posts
          </Button>
        </div>
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Schedule a post</h1>
        <p className="max-w-2xl text-muted-foreground">
          Write your content, pick a local time and IANA timezone, then schedule. The form sends an
          offset-aware timestamp so daylight-saving transitions stay correct.
        </p>
      </header>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading form…</p>}>
        <SchedulePostForm />
      </Suspense>
    </div>
  );
}
