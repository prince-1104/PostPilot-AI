import type { ReactNode } from "react";

import { Logo } from "@/components/layout/logo";
import { MobileNav } from "@/components/layout/mobile-nav";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { Badge } from "@/components/ui/badge";

/** Persistent frame around every page: sidebar on large screens, drawer on small ones. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh">
      <aside className="sticky top-0 hidden h-svh w-64 shrink-0 flex-col border-r bg-sidebar lg:flex">
        <div className="flex h-14 items-center px-5">
          <Logo />
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-4">
          <SidebarNav />
        </div>
        <p className="border-t px-5 py-4 text-xs leading-relaxed text-muted-foreground">
          Sections marked “Planned” are not built yet.
        </p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-sm lg:px-8">
          <MobileNav />
          <div className="lg:hidden">
            <Logo />
          </div>
          <Badge variant="outline" className="ml-auto text-muted-foreground">
            Phase 1 · Foundation
          </Badge>
        </header>

        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
          <div className="mx-auto w-full max-w-5xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
