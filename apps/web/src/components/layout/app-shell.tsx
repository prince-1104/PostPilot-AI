"use client";

import { Suspense, type ReactNode, useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "cn";

import { AssistantWidget } from "@/components/assistant/assistant-widget";
import { AccountSection } from "@/components/layout/account-section";
import { Logo } from "@/components/layout/logo";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { Topbar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const reduceMotion = useReducedMotion();

  return (
    <div className="flex min-h-svh">
      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 72 : 250 }}
        transition={reduceMotion ? { duration: 0 } : { type: "spring", stiffness: 320, damping: 34 }}
        className="sticky top-0 z-40 hidden h-svh shrink-0 flex-col border-r border-border/80 bg-sidebar/95 backdrop-blur-xl lg:flex"
      >
        <div
          className={cn(
            "flex h-14 items-center border-b border-border/60",
            collapsed ? "justify-center px-2" : "justify-between px-4",
          )}
        >
          <Logo collapsed={collapsed} />
          {!collapsed ? (
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label="Collapse sidebar"
              onClick={() => setCollapsed(true)}
            >
              <PanelLeftClose className="size-4" />
            </Button>
          ) : null}
        </div>

        {collapsed ? (
          <div className="flex justify-center border-b border-border/60 py-2">
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label="Expand sidebar"
              onClick={() => setCollapsed(false)}
            >
              <PanelLeftOpen className="size-4" />
            </Button>
          </div>
        ) : null}

        <div className={cn("flex-1 overflow-y-auto py-4", collapsed ? "px-2" : "px-3")}>
          <Suspense fallback={null}>
            <SidebarNav collapsed={collapsed} />
          </Suspense>
        </div>

        <AccountSection collapsed={collapsed} />
      </motion.aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <Suspense fallback={null}>
          <Topbar />
        </Suspense>

        <main className="relative flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>

      <Suspense fallback={null}>
        <AssistantWidget />
      </Suspense>
    </div>
  );
}
