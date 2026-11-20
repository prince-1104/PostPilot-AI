import {
  Activity,
  CalendarClock,
  ListChecks,
  type LucideIcon,
  Send,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface PlannedFeature {
  title: string;
  description: string;
  icon: LucideIcon;
}

const PLANNED_FEATURES: readonly PlannedFeature[] = [
  {
    title: "Post scheduling",
    description: "Write a post and choose the date and time it should be published.",
    icon: CalendarClock,
  },
  {
    title: "Background publishing",
    description:
      "Publish due posts from durable workers, with retries and protection against duplicates.",
    icon: Send,
  },
  {
    title: "Publishing status",
    description: "Follow each post from scheduled to published or failed, attempt by attempt.",
    icon: ListChecks,
  },
  {
    title: "AI writing assistant",
    description: "Draft and refine post copy with a language model before scheduling it.",
    icon: Sparkles,
  },
  {
    title: "Monitoring",
    description: "Inspect the publishing queue, worker activity, and recent failures.",
    icon: Activity,
  },
];

/** Roadmap cards. Nothing here is functional, and each card says so. */
export function PlannedFeatures() {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {PLANNED_FEATURES.map(({ title, description, icon: Icon }) => (
        <li key={title}>
          <Card className="h-full">
            <CardHeader>
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex size-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <Badge variant="secondary">Not implemented</Badge>
              </div>
              <CardTitle>{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </CardHeader>
          </Card>
        </li>
      ))}
    </ul>
  );
}
