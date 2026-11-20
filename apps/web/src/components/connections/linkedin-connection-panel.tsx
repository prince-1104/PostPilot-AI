"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Link2, Link2Off, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/lib/api/client";
import { getMe, linkedInAuthorizeUrl, logout, type UserProfile } from "@/lib/api/auth";
import {
  disconnectLinkedIn,
  getLinkedInConnection,
  type LinkedInConnection,
} from "@/lib/api/connections";

type LoadState = "loading" | "signed_out" | "ready" | "error";

interface PanelData {
  loadState: LoadState;
  user: UserProfile | null;
  connection: LinkedInConnection | null;
  error: string | null;
}

const INITIAL: PanelData = {
  loadState: "loading",
  user: null,
  connection: null,
  error: null,
};

function formatExpiry(iso: string | null): string {
  if (!iso) return "Unknown";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

async function loadPanel(signal: AbortSignal): Promise<PanelData> {
  try {
    const me = await getMe(signal);
    const status = await getLinkedInConnection(signal);
    return { loadState: "ready", user: me, connection: status, error: null };
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      return { loadState: "signed_out", user: null, connection: null, error: null };
    }
    return {
      loadState: "error",
      user: null,
      connection: null,
      error: err instanceof Error ? err.message : "Could not load connection status.",
    };
  }
}

export function LinkedInConnectionPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [data, setData] = useState<PanelData>(INITIAL);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const oauthStatus = searchParams.get("oauth");
  const oauthReason = searchParams.get("reason");

  useEffect(() => {
    const controller = new AbortController();
    void loadPanel(controller.signal).then((next) => {
      if (!controller.signal.aborted) setData(next);
    });
    return () => controller.abort();
  }, [attempt]);

  async function handleLogout() {
    setBusy(true);
    setActionError(null);
    try {
      await logout();
      setData({ loadState: "signed_out", user: null, connection: null, error: null });
      router.replace("/connections");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Logout failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    if (
      !window.confirm(
        "Disconnect LinkedIn from PostPilot? This removes the stored access token locally. " +
          "It does not revoke the grant at LinkedIn.",
      )
    ) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const status = await disconnectLinkedIn();
      setData((current) => ({
        ...current,
        connection: status,
        loadState: "ready",
      }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setData({ loadState: "signed_out", user: null, connection: null, error: null });
      } else {
        setActionError(err instanceof Error ? err.message : "Disconnect failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  const { loadState, user, connection, error } = data;

  return (
    <div className="flex flex-col gap-6">
      {oauthStatus === "success" ? (
        <p
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-900 dark:text-emerald-100"
          role="status"
        >
          LinkedIn connection completed successfully.
        </p>
      ) : null}
      {oauthStatus === "error" ? (
        <p
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          role="alert"
        >
          {oauthReason ?? "LinkedIn authorization failed."}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>LinkedIn account</CardTitle>
          <CardDescription>
            Connect the LinkedIn identity PostPilot uses for sign-in and scheduling. Automatic
            publishing to LinkedIn is not enabled yet.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {loadState === "loading" ? (
            <p className="text-sm text-muted-foreground">Loading connection status…</p>
          ) : null}

          {loadState === "error" ? (
            <p className="text-sm text-destructive" role="alert">
              {error ?? "Something went wrong."}
            </p>
          ) : null}

          {loadState === "signed_out" ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                You are not signed in. Connect with LinkedIn to create a PostPilot session.
              </p>
              <div>
                <Button render={<a href={linkedInAuthorizeUrl()} />} disabled={busy}>
                  <Link2 data-icon="inline-start" />
                  Connect with LinkedIn
                </Button>
              </div>
            </div>
          ) : null}

          {loadState === "ready" && user && connection ? (
            <div className="flex flex-col gap-5">
              <div className="flex items-start gap-4">
                {connection.avatarUrl || user.avatarUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={connection.avatarUrl ?? user.avatarUrl ?? undefined}
                    alt=""
                    className="size-14 rounded-full object-cover ring-1 ring-foreground/10"
                  />
                ) : (
                  <div className="flex size-14 items-center justify-center rounded-full bg-muted text-sm font-medium">
                    {user.displayName.slice(0, 1)}
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{connection.displayName ?? user.displayName}</p>
                  {user.email ? (
                    <p className="text-sm text-muted-foreground">{user.email}</p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge variant={connection.connected ? "default" : "secondary"}>
                      {connection.connected
                        ? "Connected"
                        : connection.reauthorizationRequired
                          ? "Reauthorization required"
                          : "Disconnected"}
                    </Badge>
                    <Badge variant="outline">{connection.connectionStatus}</Badge>
                  </div>
                </div>
              </div>

              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">Token expires</dt>
                  <dd className="font-medium">{formatExpiry(connection.tokenExpiresAt)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Granted scopes</dt>
                  <dd className="font-medium">
                    {connection.grantedScopes.length > 0
                      ? connection.grantedScopes.join(", ")
                      : "None stored"}
                  </dd>
                </div>
              </dl>

              {connection.reauthorizationRequired ? (
                <p className="text-sm text-amber-700 dark:text-amber-300">
                  The stored LinkedIn access token is missing or expired. LinkedIn does not
                  issue refresh tokens for this flow, so reconnect to continue.
                </p>
              ) : null}

              {actionError ? (
                <p className="text-sm text-destructive" role="alert">
                  {actionError}
                </p>
              ) : null}
            </div>
          ) : null}
        </CardContent>
        <CardFooter className="flex flex-wrap gap-2 border-t py-4">
          {loadState === "ready" && connection ? (
            <>
              {connection.connected ? (
                <Button variant="outline" onClick={() => void handleDisconnect()} disabled={busy}>
                  <Link2Off data-icon="inline-start" />
                  Disconnect
                </Button>
              ) : (
                <Button render={<a href={linkedInAuthorizeUrl()} />} disabled={busy}>
                  <RefreshCw data-icon="inline-start" />
                  Reconnect LinkedIn
                </Button>
              )}
              <Button variant="ghost" onClick={() => void handleLogout()} disabled={busy}>
                Sign out
              </Button>
            </>
          ) : null}
          {loadState === "error" ? (
            <Button
              variant="outline"
              onClick={() => {
                setData(INITIAL);
                setAttempt((n) => n + 1);
              }}
              disabled={busy}
            >
              Try again
            </Button>
          ) : null}
        </CardFooter>
      </Card>

      {loadState === "ready" && connection?.disconnectIsLocalOnly ? (
        <p className="text-xs text-muted-foreground">
          Disconnecting here clears PostPilot&apos;s stored LinkedIn credentials only. It does
          not revoke the OAuth grant on LinkedIn&apos;s side.
        </p>
      ) : null}
    </div>
  );
}
