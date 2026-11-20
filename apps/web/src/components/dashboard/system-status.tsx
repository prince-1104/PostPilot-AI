"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/lib/api/client";
import { DEPENDENCY_UNAVAILABLE, getReadiness, READINESS_PATH } from "@/lib/api/health";
import { env } from "@/lib/env";

const REQUEST_TIMEOUT_MS = 8000;

type CheckState = "checking" | "ok" | "down" | "unknown";

interface StatusView {
  api: CheckState;
  database: CheckState;
  /** Explanation shown when something is not healthy. */
  detail: string | null;
  /** Correlates a failed check with the API's logs. */
  requestId: string | null;
}

const CHECKING: StatusView = {
  api: "checking",
  database: "checking",
  detail: null,
  requestId: null,
};

/** Calls the readiness endpoint and maps every outcome to something displayable. */
async function loadStatus(signal: AbortSignal): Promise<StatusView> {
  try {
    await getReadiness(AbortSignal.any([signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]));
    return { api: "ok", database: "ok", detail: null, requestId: null };
  } catch (error) {
    if (error instanceof ApiError) {
      // The API responded, so it is up. A 503 with this code means PostgreSQL is not.
      const databaseDown = error.status === 503 && error.code === DEPENDENCY_UNAVAILABLE;
      return {
        api: "ok",
        database: databaseDown ? "down" : "unknown",
        detail: error.message,
        requestId: error.requestId,
      };
    }
    return {
      api: "down",
      database: "unknown",
      detail:
        "The API did not return a usable response. Check that it is running and that " +
        "this page's origin is listed in CORS_ALLOWED_ORIGINS.",
      requestId: null,
    };
  }
}

const STATE_STYLES: Record<CheckState, { dot: string; text: string }> = {
  checking: { dot: "bg-muted-foreground/40 animate-pulse", text: "text-muted-foreground" },
  ok: { dot: "bg-emerald-500", text: "text-foreground" },
  down: { dot: "bg-destructive", text: "text-destructive" },
  unknown: { dot: "bg-amber-500", text: "text-muted-foreground" },
};

const API_LABELS: Record<CheckState, string> = {
  checking: "Checking…",
  ok: "Reachable",
  down: "Unreachable",
  unknown: "Unknown",
};

const DATABASE_LABELS: Record<CheckState, string> = {
  checking: "Checking…",
  ok: "Connected",
  down: "Unavailable",
  unknown: "Unknown",
};

function StatusRow({ name, state, label }: { name: string; state: CheckState; label: string }) {
  const styles = STATE_STYLES[state];
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <dt className="text-muted-foreground">{name}</dt>
      <dd className={cn("flex items-center gap-2 font-medium", styles.text)}>
        <span className={cn("size-2 rounded-full", styles.dot)} aria-hidden="true" />
        {label}
      </dd>
    </div>
  );
}

/** Live status of the API and its database, read from the readiness endpoint. */
export function SystemStatus() {
  const [status, setStatus] = useState<StatusView>(CHECKING);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void loadStatus(controller.signal).then((next) => {
      // Ignore a result that belongs to an unmounted component or a superseded check.
      if (!controller.signal.aborted) setStatus(next);
    });
    return () => controller.abort();
  }, [attempt]);

  function checkAgain() {
    setStatus(CHECKING);
    setAttempt((current) => current + 1);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>System status</CardTitle>
        <CardDescription>Live result from the API readiness endpoint.</CardDescription>
        <CardAction>
          <Button
            variant="outline"
            size="sm"
            onClick={checkAgain}
            disabled={status.api === "checking"}
          >
            <RefreshCw data-icon="inline-start" aria-hidden="true" />
            Check again
          </Button>
        </CardAction>
      </CardHeader>

      <CardContent>
        <dl className="divide-y" aria-live="polite">
          <StatusRow name="API" state={status.api} label={API_LABELS[status.api]} />
          <StatusRow
            name="PostgreSQL"
            state={status.database}
            label={DATABASE_LABELS[status.database]}
          />
        </dl>
        {status.detail !== null && (
          <p role="status" className="mt-3 rounded-lg bg-muted px-3 py-2 text-muted-foreground">
            {status.detail}
            {status.requestId !== null && (
              <span className="mt-1 block font-mono text-xs">Request ID: {status.requestId}</span>
            )}
          </p>
        )}
      </CardContent>

      <CardFooter className="font-mono text-xs break-all text-muted-foreground">
        GET {env.apiBaseUrl}
        {READINESS_PATH}
      </CardFooter>
    </Card>
  );
}
