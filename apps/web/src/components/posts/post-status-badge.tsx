import { cn } from "cn";

import type { PostStatus } from "@/lib/api/posts";

const LABELS: Record<PostStatus, string> = {
  scheduled: "Scheduled",
  processing: "Processing",
  published: "Published",
  failed: "Failed",
  cancelled: "Cancelled",
  requires_review: "Requires review",
};

const STYLES: Record<PostStatus, string> = {
  scheduled: "border-electric-blue/35 bg-electric-blue/10 text-electric-blue",
  processing: "border-cyan/35 bg-cyan/10 text-cyan",
  published: "border-emerald/35 bg-emerald/10 text-emerald",
  failed: "border-rose/35 bg-rose/10 text-rose",
  cancelled: "border-border bg-surface text-muted-foreground",
  requires_review: "border-amber/35 bg-amber/10 text-amber",
};

export function PostStatusBadge({
  status,
  className,
}: {
  status: PostStatus;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-wide",
        STYLES[status],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current opacity-80" aria-hidden />
      {LABELS[status]}
    </span>
  );
}
