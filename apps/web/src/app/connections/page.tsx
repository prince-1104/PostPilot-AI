import type { Metadata } from "next";
import { Suspense } from "react";

import { LinkedInConnectionPanel } from "@/components/connections/linkedin-connection-panel";

export const metadata: Metadata = {
  title: { absolute: "Connections · PostPilot AI" },
};

export default function ConnectionsPage() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Connections</h1>
        <p className="max-w-2xl text-muted-foreground">
          Manage the LinkedIn account linked to PostPilot. Once connected, schedule posts from the
          Posts page. Publishing to LinkedIn is not enabled yet.
        </p>
      </header>

      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <LinkedInConnectionPanel />
      </Suspense>
    </div>
  );
}
