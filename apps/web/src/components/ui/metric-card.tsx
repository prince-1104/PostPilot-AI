"use client";

import type { LucideIcon } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "cn";

import { Skeleton } from "@/components/ui/skeleton-loader";

type Accent = "violet" | "blue" | "cyan" | "emerald" | "amber" | "rose";

const ACCENT: Record<Accent, { icon: string; value: string; ring: string }> = {
  violet: {
    icon: "bg-violet/15 text-violet-light",
    value: "text-foreground",
    ring: "ring-violet/20",
  },
  blue: {
    icon: "bg-electric-blue/15 text-electric-blue",
    value: "text-foreground",
    ring: "ring-electric-blue/20",
  },
  cyan: {
    icon: "bg-cyan/15 text-cyan",
    value: "text-foreground",
    ring: "ring-cyan/20",
  },
  emerald: {
    icon: "bg-emerald/15 text-emerald",
    value: "text-foreground",
    ring: "ring-emerald/20",
  },
  amber: {
    icon: "bg-amber/15 text-amber",
    value: "text-foreground",
    ring: "ring-amber/20",
  },
  rose: {
    icon: "bg-rose/15 text-rose",
    value: "text-foreground",
    ring: "ring-rose/20",
  },
};

interface MetricCardProps {
  label: string;
  value: string | number | null;
  icon: LucideIcon;
  accent?: Accent;
  loading?: boolean;
  hint?: string;
}

export function MetricCard({
  label,
  value,
  icon: Icon,
  accent = "violet",
  loading = false,
  hint,
}: MetricCardProps) {
  const styles = ACCENT[accent];
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "surface-panel rounded-2xl p-4 ring-1 ring-inset transition-colors hover:bg-surface-hover/40",
        styles.ring,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {label}
          </p>
          {loading ? (
            <Skeleton className="h-8 w-16" />
          ) : (
            <p className={cn("font-heading text-3xl font-semibold tracking-tight", styles.value)}>
              {value ?? "—"}
            </p>
          )}
          {hint ? <p className="font-meta">{hint}</p> : null}
        </div>
        <span
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-xl",
            styles.icon,
          )}
        >
          <Icon className="size-5" aria-hidden />
        </span>
      </div>
    </motion.div>
  );
}
