import type { Metadata } from "next";
import { Suspense } from "react";

import { LinkedInConnectionPanel } from "@/components/connections/linkedin-connection-panel";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton-loader";

export const metadata: Metadata = {
  title: { absolute: "Connections · PostPilot AI" },
};

export default function ConnectionsPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Publishing"
        title="Connections"
        description="Manage the LinkedIn account linked to PostPilot — status, scopes, token expiry, and publishing readiness."
      />
      <Suspense fallback={<Skeleton className="h-48 w-full max-w-xl rounded-2xl" />}>
        <LinkedInConnectionPanel />
      </Suspense>
    </div>
  );
}
