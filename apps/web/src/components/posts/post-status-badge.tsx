import { Badge } from "@/components/ui/badge";
import type { PostStatus } from "@/lib/api/posts";

const LABELS: Record<PostStatus, string> = {
  scheduled: "Scheduled",
  processing: "Processing",
  published: "Published",
  failed: "Failed",
  cancelled: "Cancelled",
  requires_review: "Requires review",
};

export function PostStatusBadge({ status }: { status: PostStatus }) {
  const variant =
    status === "cancelled" || status === "failed"
      ? "secondary"
      : status === "published"
        ? "default"
        : status === "requires_review" || status === "processing"
          ? "outline"
          : "outline";
  return <Badge variant={variant}>{LABELS[status]}</Badge>;
}
