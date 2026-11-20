import Link from "next/link";
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

interface FeatureCard {
  title: string;
  description: string;
  icon: LucideIcon;
  status: "available" | "planned";
  href?: string;
}

const FEATURES: readonly FeatureCard[] = [
  {
    title: "Post scheduling",
    description: "Write a post, pick a timezone-aware time, and cancel or reschedule before publish.",
    icon: CalendarClock,
    status: "available",
    href: "/posts",
  },
  {
    title: "Background publishing",
    description:
      "Publish due posts from durable workers, with retries and protection against duplicates.",
    icon: Send,
    status: "planned",
  },
  {
    title: "Publishing status",
    description: "Follow each post from scheduled to published or failed, attempt by attempt.",
    icon: ListChecks,
    status: "planned",
  },
  {
    title: "AI writing assistant",
    description: "Draft and refine post copy with a language model before scheduling it.",
    icon: Sparkles,
    status: "planned",
  },
  {
    title: "Monitoring",
    description: "Inspect the publishing queue, worker activity, and recent failures.",
    icon: Activity,
    status: "planned",
  },
];

/** Product roadmap. Available items link into the app; planned items say so explicitly. */
export function PlannedFeatures() {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {FEATURES.map(({ title, description, icon: Icon, status, href }) => (
        <li key={title}>
          <Card className="h-full">
            <CardHeader>
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex size-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <Badge variant={status === "available" ? "default" : "secondary"}>
                  {status === "available" ? "Available" : "Not implemented"}
                </Badge>
              </div>
              <CardTitle>{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
              {href ? (
                <Link
                  href="/posts"
                  className="mt-2 text-sm font-medium text-brand underline-offset-4 hover:underline"
                >
                  Open posts
                </Link>
              ) : null}
            </CardHeader>
          </Card>
        </li>
      ))}
    </ul>
  );
}
