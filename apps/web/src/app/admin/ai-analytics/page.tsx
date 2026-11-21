"use client";

import { useEffect, useState, useTransition } from "react";

import { MetricCard } from "@/components/ui/metric-card";
import { PageHeader } from "@/components/ui/page-header";
import { PremiumCard } from "@/components/ui/premium-card";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  type AiAnalyticsSummary,
  type ThreadInspection,
  getAiAnalytics,
  inspectAiThread,
} from "@/lib/api/ai-analytics";
import {
  Activity,
  AlertTriangle,
  CircleDollarSign,
  Clock3,
  FileText,
  Sparkles,
  Zap,
} from "lucide-react";

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
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Operations · Admin"
        title="AI analytics"
        description="Real LLM usage, estimated API cost, latency, and scheduling conversions. Costs are estimates from frozen pricing versions — not provider invoices."
      />

      {forbidden ? (
        <p className="rounded-xl border border-amber/30 bg-amber/10 px-4 py-3 text-sm text-amber">
          Administrator access required. Ask an operator to add your user id or email to
          ADMIN_USER_IDS / ADMIN_EMAILS.
        </p>
      ) : null}

      {error ? (
        <p className="rounded-xl border border-rose/30 bg-rose/10 px-4 py-3 text-sm text-rose" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {(["24h", "7d", "30d"] as const).map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={preset === value ? "default" : "outline"}
            className={preset === value ? "gradient-primary border-0 text-white" : "bg-surface/40"}
            onClick={() => setPreset(value)}
          >
            Last {value}
          </Button>
        ))}
        {pending ? <span className="font-meta">Refreshing…</span> : null}
      </div>

      {summary ? (
        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="LLM requests"
            value={summary.total_llm_requests}
            icon={Zap}
            accent="violet"
          />
          <MetricCard
            label="Input tokens"
            value={formatTokens(summary.total_input_tokens)}
            icon={Activity}
            accent="blue"
          />
          <MetricCard
            label="Output tokens"
            value={formatTokens(summary.total_output_tokens)}
            icon={Sparkles}
            accent="cyan"
          />
          <MetricCard
            label="Estimated cost"
            value={formatCost(
              summary.total_estimated_cost,
              summary.cost_currency,
              summary.cost_label,
            )}
            icon={CircleDollarSign}
            accent="emerald"
          />
          <MetricCard
            label="Avg / p95 latency"
            value={`${summary.avg_latency_ms?.toFixed(0) ?? "—"} / ${summary.p95_latency_ms?.toFixed(0) ?? "—"} ms`}
            icon={Clock3}
            accent="blue"
          />
          <MetricCard
            label="Failed LLM requests"
            value={summary.failed_llm_requests}
            icon={AlertTriangle}
            accent="rose"
          />
          <MetricCard
            label="Drafts generated"
            value={summary.drafts_generated}
            icon={FileText}
            accent="violet"
          />
          <MetricCard
            label="AI drafts scheduled"
            value={summary.approved_ai_drafts_scheduled}
            icon={Sparkles}
            accent="emerald"
          />
        </section>
      ) : null}

      {summary ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <PremiumCard className="space-y-3">
            <h2 className="font-heading text-base font-medium">Quality signals</h2>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Review failure rate</dt>
                <dd className="font-medium">
                  {summary.review_failure_rate == null
                    ? "—"
                    : `${(summary.review_failure_rate * 100).toFixed(1)}%`}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Automatic revisions</dt>
                <dd className="font-medium">{summary.automatic_revision_traces}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Usage unknown</dt>
                <dd className="font-meta">{summary.usage_unknown_requests}</dd>
              </div>
            </dl>
          </PremiumCard>

          {summary.requests_by_model.length > 0 ? (
            <PremiumCard className="space-y-3">
              <h2 className="font-heading text-base font-medium">Requests by model</h2>
              <ul className="divide-y divide-border/80">
                {summary.requests_by_model.map((row) => (
                  <li
                    key={`${String(row.provider)}-${String(row.model)}`}
                    className="flex items-center justify-between gap-3 py-2.5 text-sm"
                  >
                    <span className="font-meta truncate">
                      {String(row.provider)} / {String(row.model)}
                    </span>
                    <span className="font-medium">{String(row.requests)} req</span>
                  </li>
                ))}
              </ul>
            </PremiumCard>
          ) : null}
        </div>
      ) : null}

      <PremiumCard className="space-y-4">
        <div>
          <h2 className="font-heading text-base font-medium">Thread inspection</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Trace metadata only — prompts, message bodies, and credentials are omitted.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            value={threadId}
            onChange={(event) => setThreadId(event.target.value)}
            placeholder="Thread UUID"
            className="min-w-[16rem] flex-1 rounded-xl border border-input bg-background-elevated px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-violet/40"
          />
          <Button type="button" onClick={onInspect} className="gradient-primary border-0 text-white">
            Inspect
          </Button>
        </div>
        {inspection ? (
          <pre className="overflow-auto rounded-xl border border-border bg-background p-4 font-mono text-xs text-muted-foreground">
            {JSON.stringify(inspection, null, 2)}
          </pre>
        ) : null}
      </PremiumCard>
    </div>
  );
}
