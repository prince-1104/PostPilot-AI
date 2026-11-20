"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";

import { NAV_ITEMS } from "@/components/layout/navigation";

interface SidebarNavProps {
  /** Called after a link is followed, so a containing drawer can close. */
  onNavigate?: () => void;
}

const ITEM_CLASSES = "flex items-center gap-3 rounded-lg px-3 py-2 text-sm";

export function SidebarNav({ onNavigate }: SidebarNavProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main">
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ label, icon: Icon, href }) => {
          if (href === undefined) {
            return (
              <li key={label}>
                <span className={cn(ITEM_CLASSES, "text-muted-foreground/70")}>
                  <Icon className="size-4 shrink-0" aria-hidden="true" />
                  <span className="flex-1 truncate">{label}</span>
                  <span className="rounded-full border px-1.5 py-px text-[0.65rem] font-medium tracking-wide uppercase">
                    Planned
                  </span>
                </span>
              </li>
            );
          }

          const isActive = pathname === href;
          return (
            <li key={label}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  ITEM_CLASSES,
                  "font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                )}
              >
                <Icon className="size-4 shrink-0" aria-hidden="true" />
                <span className="truncate">{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
