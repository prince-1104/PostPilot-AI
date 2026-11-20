"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api/client";
import { getPublishingReadiness, type PublishingReadiness } from "@/lib/api/publishing";

function labelFor(readiness: PublishingReadiness | null, signedOut: boolean): string {
  if (signedOut) return "Sign in to publish";
  if (!readiness) return "Publishing…";
  if (readiness.publishProvider === "linkedin" && readiness.enableRealPublishing) {
    if (readiness.livePublishRequireCanary) {
      return readiness.canaryPostIds.length > 0
        ? "LinkedIn live · canary"
        : "LinkedIn live · canary locked";
    }
    return "LinkedIn live publishing";
  }
  return "LinkedIn publishing idle";
}

/** Header badge reflecting real provider config — never implies fake success. */
export function ProviderStatusBadge() {
  const [readiness, setReadiness] = useState<PublishingReadiness | null>(null);
  const [signedOut, setSignedOut] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void getPublishingReadiness(null, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setReadiness(data);
          setSignedOut(false);
        }
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setSignedOut(true);
          setReadiness(null);
          return;
        }
        setReadiness(null);
      });
    return () => controller.abort();
  }, []);

  return (
    <Badge variant="outline" className="ml-auto text-muted-foreground">
      {labelFor(readiness, signedOut)}
    </Badge>
  );
}
