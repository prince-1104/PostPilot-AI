import type { Metadata } from "next";

import { PlannedFeatures } from "@/components/dashboard/planned-features";
import { SystemStatus } from "@/components/dashboard/system-status";

export const metadata: Metadata = {
  // The root layout's title template only applies to nested route segments, and this
  // page shares the layout's segment, so the full title is spelled out.
  title: { absolute: "Dashboard · PostPilot AI" },
};

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="max-w-2xl text-muted-foreground">
          PostPilot AI is in its foundation phase. The application shell, API, database, and
          queue infrastructure are in place. No product features are implemented yet, so
          there is no account, post, or publishing data to show.
        </p>
      </header>

      <section aria-labelledby="system-status-heading" className="flex flex-col gap-4">
        <h2 id="system-status-heading" className="font-heading text-lg font-medium">
          What is running
        </h2>
        <div className="max-w-xl">
          <SystemStatus />
        </div>
      </section>

      <section aria-labelledby="planned-features-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 id="planned-features-heading" className="font-heading text-lg font-medium">
            Planned features
          </h2>
          <p className="text-sm text-muted-foreground">
            Scheduled for later phases. None of these work today.
          </p>
        </div>
        <PlannedFeatures />
      </section>
    </div>
  );
}
