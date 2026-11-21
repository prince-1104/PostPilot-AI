"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "cn";

import { NAV_GROUPS } from "@/components/layout/navigation";

interface SidebarNavProps {
  onNavigate?: () => void;
  collapsed?: boolean;
}

function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/posts/new") return pathname.startsWith("/posts/new");
  if (href === "/posts") {
    return pathname === "/posts" || (pathname.startsWith("/posts/") && !pathname.startsWith("/posts/new"));
  }
  if (href === "/assistant") return pathname.startsWith("/assistant");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarNav({ onNavigate, collapsed = false }: SidebarNavProps) {
  const pathname = usePathname();
  const reduceMotion = useReducedMotion();

  return (
    <nav aria-label="Main" className="flex flex-col gap-6">
      {NAV_GROUPS.map((group) => (
        <div key={group.id} className="flex flex-col gap-1">
          {!collapsed ? (
            <p className="px-3 pb-1 font-mono text-[10px] font-medium tracking-[0.16em] text-muted-foreground/80 uppercase">
              {group.label}
            </p>
          ) : (
            <span className="sr-only">{group.label}</span>
          )}
          <ul className="flex flex-col gap-0.5">
            {group.items.map(({ label, icon: Icon, href }) => {
              const active = isActivePath(pathname, href);
              return (
                <li key={`${group.id}-${href}-${label}`}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    title={collapsed ? label : undefined}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium outline-none transition-colors",
                      "focus-visible:ring-3 focus-visible:ring-violet/40",
                      collapsed && "justify-center px-2",
                      active
                        ? "bg-surface-active text-foreground"
                        : "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
                    )}
                  >
                    {active ? (
                      <motion.span
                        layoutId={reduceMotion ? undefined : "nav-active"}
                        className="absolute top-1/2 left-0 h-5 w-0.5 -translate-y-1/2 rounded-full bg-gradient-to-b from-violet to-cyan"
                        aria-hidden
                      />
                    ) : null}
                    <Icon
                      className={cn("size-4 shrink-0", active && "text-violet-light")}
                      aria-hidden
                    />
                    {!collapsed ? <span className="truncate">{label}</span> : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
