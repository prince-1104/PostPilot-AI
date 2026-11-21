import {
  Activity,
  CalendarClock,
  CalendarPlus,
  LayoutDashboard,
  type LucideIcon,
  Sparkles,
  UserRoundCheck,
} from "lucide-react";
import type { Route } from "next";

export type NavGroupId = "overview" | "publishing" | "ai" | "operations";

export interface NavItem {
  label: string;
  icon: LucideIcon;
  href: Route;
  /** Soft-gate: page enforces admin auth; hide only if you know user is non-admin. */
  adminOnly?: boolean;
}

export interface NavGroup {
  id: NavGroupId;
  label: string;
  items: readonly NavItem[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    id: "overview",
    label: "Overview",
    items: [{ label: "Dashboard", icon: LayoutDashboard, href: "/" }],
  },
  {
    id: "publishing",
    label: "Publishing",
    items: [
      { label: "Posts", icon: CalendarClock, href: "/posts" },
      { label: "Schedule", icon: CalendarPlus, href: "/posts/new" },
      { label: "Connections", icon: UserRoundCheck, href: "/connections" },
    ],
  },
  {
    id: "ai",
    label: "AI Workspace",
    items: [{ label: "AI Studio", icon: Sparkles, href: "/assistant" }],
  },
  {
    id: "operations",
    label: "Operations",
    items: [
      {
        label: "AI Analytics",
        icon: Activity,
        href: "/admin/ai-analytics",
        adminOnly: true,
      },
    ],
  },
];

/** Flat list for active-route matching and breadcrumbs. */
export const NAV_ITEMS: readonly NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

export function pageTitleForPath(pathname: string): string {
  if (pathname.startsWith("/posts/new")) return "Schedule";
  if (pathname.startsWith("/posts/")) return "Post detail";
  if (pathname.startsWith("/posts")) return "Posts";
  if (pathname.startsWith("/connections")) return "Connections";
  if (pathname.startsWith("/assistant")) return "AI Studio";
  if (pathname.startsWith("/admin/ai-analytics")) return "AI Analytics";
  return "Dashboard";
}
