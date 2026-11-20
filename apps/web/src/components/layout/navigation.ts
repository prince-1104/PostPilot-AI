import {
  Activity,
  CalendarClock,
  LayoutDashboard,
  type LucideIcon,
  Sparkles,
  UserRoundCheck,
} from "lucide-react";
import type { Route } from "next";

export interface NavItem {
  label: string;
  icon: LucideIcon;
  /** Present only for sections that exist. Items without it render as planned. */
  href?: Route;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { label: "Dashboard", icon: LayoutDashboard, href: "/" },
  { label: "Connections", icon: UserRoundCheck, href: "/connections" },
  { label: "Posts", icon: CalendarClock, href: "/posts" },
  { label: "AI assistant", icon: Sparkles },
  { label: "Monitoring", icon: Activity },
];
