"use client";

import { useEffect, useState, useTransition } from "react";
import { ApiError } from "@/lib/api/client";
import {
  type AiAnalyticsSummary,
  type ThreadInspection,
  getAiAnalytics,
  inspectAiThread,
} from "@/lib/api/ai-analytics";

type Preset = "24h" | "7d" | "30d";

function formatCost(value: number | null, currency: string, label: string): string {
  if (value == null) return "unavailable";
  return `${currency} ${value.toFixed(6)} (${label})`;
}

function formatTokens(value: number | null): string {
  return value == null ? "unknown" : value.toLocaleString();
}

export default function AiAnalyticsPage() {
  const [preset, setPreset] = useState<Preset>("7d");
  const [summary, setSummary] = useState<AiAnalyticsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [threadId, setThreadId] = useState("");
  const [inspection, setInspection] = useState<ThreadInspection | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    const controller = new AbortController();
    startTransition(async () => {
      setError(null);
      setForbidden(false);
      try {
        const data = await getAiAnalytics(preset, controller.signal);
        setSummary(data);
      } catch (err) {
        if (err instanceof ApiError && err.status === 403) {
          setForbidden(true);
          setSummary(null);
          return;
        }
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Failed to load analytics");
      }
    });
    return () => controller.abort();
  }, [preset]);

  function onInspect() {
    const id = threadId.trim();
    if (!id) return;
    startTransition(async () => {
      setError(null);
      try {
        setInspection(await inspectAiThread(id));
      } catch (err) {
        setInspection(null);
        setError(err instanceof Error ? err.message : "Inspection failed");
      }
    });
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-10">
      <header className="space-y-2">
        <p className="text-sm uppercase tracking-[0.2em] text-zinc-500">Admin</p>
        <h1 className="font-display text-3xl text-zinc-900">AI analytics</h1>
        <p className="max-w-2xl text-sm text-zinc-600">
          Real LLM usage, estimated API cost, latency, and scheduling conversions.
          Costs are estimates from frozen pricing versions — not official provider invoices.
        </p>
      </header>

      {forbidden ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Administrator access required. Ask an operator to add your user id or email to
          ADMIN_USER_IDS / ADMIN_EMAILS.
        </p>
      ) : null}

      {error ? (
        <p className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {(["24h", "7d", "30d"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setPreset(value)}
            className={
              preset === value
                ? "rounded-md bg-zinc-900 px-3 py-1.5 text-sm text-white"
                : "rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700"
            }
          >
            Last {value}
          </button>
        ))}
        {pending ? <span className="text-sm text-zinc-500">Refreshing…</span> : null}
      </div>

      {summary ? (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Metric label="LLM requests" value={String(summary.total_llm_requests)} />
          <Metric
            label="Input tokens"
            value={formatTokens(summary.total_input_tokens)}
          />
          <Metric
            label="Output tokens"
            value={formatTokens(summary.total_output_tokens)}
          />
          <Metric
            label="Estimated API cost"
            value={formatCost(
              summary.total_estimated_cost,
              summary.cost_currency,
              summary.cost_label,
            )}
          />
          <Metric
            label="Avg / p95 latency"
            value={`${summary.avg_latency_ms?.toFixed(0) ?? "—"} / ${summary.p95_latency_ms?.toFixed(0) ?? "—"} ms`}
          />
          <Metric label="Failed LLM requests" value={String(summary.failed_llm_requests)} />
          <Metric
            label="Review failure rate"
            value={
              summary.review_failure_rate == null
                ? "—"
                : `${(summary.review_failure_rate * 100).toFixed(1)}%`
            }
          />
          <Metric
            label="Automatic revisions"
            value={String(summary.automatic_revision_traces)}
          />
          <Metric label="Drafts generated" value={String(summary.drafts_generated)} />
          <Metric
            label="AI drafts scheduled"
            value={String(summary.approved_ai_drafts_scheduled)}
          />
          <Metric
            label="Usage unknown"
            value={String(summary.usage_unknown_requests)}
          />
        </section>
      ) : null}

      {summary && summary.requests_by_model.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-lg font-medium text-zinc-900">Requests by model</h2>
          <ul className="divide-y divide-zinc-200 border border-zinc-200">
            {summary.requests_by_model.map((row) => (
              <li key={String(row.model)} className="flex justify-between px-3 py-2 text-sm">
                <span>
                  {String(row.provider)} / {String(row.model)}
                </span>
                <span>{String(row.requests)} req</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="space-y-3 border-t border-zinc-200 pt-6">
        <h2 className="text-lg font-medium text-zinc-900">Thread inspection</h2>
        <p className="text-sm text-zinc-600">
          Trace metadata only — prompts, message bodies, and credentials are omitted.
        </p>
        <div className="flex flex-wrap gap-2">
          <input
            value={threadId}
            onChange={(event) => setThreadId(event.target.value)}
            placeholder="Thread UUID"
            className="min-w-[16rem] flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={onInspect}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white"
          >
            Inspect
          </button>
        </div>
        {inspection ? (
          <pre className="overflow-auto rounded-md bg-zinc-950 p-4 text-xs text-zinc-100">
            {JSON.stringify(inspection, null, 2)}
          </pre>
        ) : null}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-zinc-200 px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-lg text-zinc-900">{value}</p>
    </div>
  );
}
