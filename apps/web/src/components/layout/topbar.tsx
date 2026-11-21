"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus, Sparkles } from "lucide-react";

import { pageTitleForPath } from "@/components/layout/navigation";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ProviderStatusBadge } from "@/components/publishing/provider-status-badge";
import { Button } from "@/components/ui/button";

export function Topbar() {
  const pathname = usePathname();
  const title = pageTitleForPath(pathname);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border/80 bg-background/70 px-4 backdrop-blur-xl lg:px-6">
      <MobileNav />
      <div className="min-w-0 flex-1">
        <p className="truncate font-heading text-sm font-medium tracking-tight text-foreground">
          {title}
        </p>
      </div>
      <div className="hidden items-center gap-2 sm:flex">
        <ProviderStatusBadge />
      </div>
      <Button
        size="sm"
        variant="outline"
        render={<Link href="/assistant" />}
        className="hidden border-border bg-surface/60 sm:inline-flex"
      >
        <Sparkles data-icon="inline-start" className="text-violet-light" />
        AI Studio
      </Button>
      <Button
        size="sm"
        render={<Link href="/posts/new" />}
        className="gradient-primary border-0 text-white shadow-[0_0_24px_-8px_rgb(139_92_246_/_0.65)] hover:brightness-110"
      >
        <Plus data-icon="inline-start" />
        New Post
      </Button>
    </header>
  );
}
