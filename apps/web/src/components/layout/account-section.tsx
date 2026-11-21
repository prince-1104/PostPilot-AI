"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { getMe, logout, type UserProfile } from "@/lib/api/auth";

interface AccountSectionProps {
  collapsed?: boolean;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return `${parts[0]![0] ?? ""}${parts[1]![0] ?? ""}`.toUpperCase();
}

export function AccountSection({ collapsed = false }: AccountSectionProps) {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void getMe(controller.signal)
      .then((profile) => {
        if (!controller.signal.aborted) {
          setUser(profile);
          setLoaded(true);
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (!(error instanceof ApiError && error.status === 401)) {
          // Quiet shell; connections page shows detail.
        }
        setUser(null);
        setLoaded(true);
      });
    return () => controller.abort();
  }, []);

  if (!loaded) {
    return (
      <div
        className={cn(
          "border-t border-border/60 px-4 py-4 text-xs text-muted-foreground",
          collapsed && "px-2 text-center",
        )}
      >
        {collapsed ? "…" : "Checking session…"}
      </div>
    );
  }

  if (!user) {
    return (
      <div className={cn("flex flex-col gap-2 border-t border-border/60 px-4 py-4", collapsed && "px-2")}>
        {!collapsed ? <p className="text-xs text-muted-foreground">Not signed in</p> : null}
        <Button
          size="sm"
          variant="outline"
          render={<Link href="/connections" />}
          className="w-full justify-center"
          title="Connect LinkedIn"
        >
          {collapsed ? "In" : "Connect LinkedIn"}
        </Button>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-2 border-t border-border/60 px-4 py-4", collapsed && "items-center px-2")}>
      <div className={cn("flex items-center gap-3", collapsed && "justify-center")}>
        <span
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-active text-xs font-semibold text-violet-light ring-1 ring-border"
          title={user.displayName}
        >
          {initials(user.displayName)}
        </span>
        {!collapsed ? (
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{user.displayName}</p>
            {user.email ? (
              <p className="truncate font-mono text-[11px] text-muted-foreground">{user.email}</p>
            ) : null}
          </div>
        ) : null}
      </div>
      {!collapsed ? (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            render={<Link href="/connections" />}
            className="flex-1 justify-center"
          >
            Account
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="flex-1 justify-center"
            onClick={() => {
              void logout().then(() => {
                setUser(null);
                router.push("/connections");
              });
            }}
          >
            Sign out
          </Button>
        </div>
      ) : null}
    </div>
  );
}
