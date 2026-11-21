import type { Metadata } from "next";
import { Suspense } from "react";

import { AssistantStudio } from "@/components/assistant/assistant-studio";
import { Skeleton } from "@/components/ui/skeleton-loader";

export const metadata: Metadata = {
  title: { absolute: "AI Studio · PostPilot AI" },
};

export default function AssistantPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[70vh] w-full rounded-2xl" />}>
      <AssistantStudio />
    </Suspense>
  );
}
