"use client";

import type { ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "cn";

interface PremiumCardProps {
  children: ReactNode;
  className?: string;
  glow?: "violet" | "blue" | "cyan" | "none";
  interactive?: boolean;
}

const GLOW: Record<Exclude<PremiumCardProps["glow"], undefined>, string> = {
  violet: "hover:shadow-[0_0_40px_-16px_rgb(139_92_246_/_0.45)]",
  blue: "hover:shadow-[0_0_40px_-16px_rgb(59_130_246_/_0.4)]",
  cyan: "hover:shadow-[0_0_40px_-16px_rgb(34_211_238_/_0.35)]",
  none: "",
};

export function PremiumCard({
  children,
  className,
  glow = "none",
  interactive = false,
}: PremiumCardProps) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      whileHover={
        interactive && !reduceMotion ? { y: -2, transition: { duration: 0.18 } } : undefined
      }
      className={cn(
        "surface-panel rounded-2xl p-5 transition-[border-color,box-shadow] duration-200",
        interactive && "hover:border-border-strong",
        GLOW[glow],
        className,
      )}
    >
      {children}
    </motion.div>
  );
}
