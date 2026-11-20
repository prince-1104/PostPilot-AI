"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { getMe, logout, type UserProfile } from "@/lib/api/auth";

export function AccountSection() {
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
          // Keep the shell quiet for transient failures; the connections page shows detail.
        }
        setUser(null);
        setLoaded(true);
      });
    return () => controller.abort();
  }, []);

  if (!loaded) {
    return (
      <div className="border-t px-5 py-4 text-xs text-muted-foreground">Checking session…</div>
    );
  }

  if (!user) {
    return (
      <div className="flex flex-col gap-2 border-t px-5 py-4">
        <p className="text-xs text-muted-foreground">Not signed in</p>
        <Button
          size="sm"
          variant="outline"
          render={<Link href="/connections" />}
          className="w-full justify-center"
        >
          Connect LinkedIn
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 border-t px-5 py-4">
      <p className="truncate text-sm font-medium">{user.displayName}</p>
      {user.email ? (
        <p className="truncate text-xs text-muted-foreground">{user.email}</p>
      ) : null}
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
    </div>
  );
}
