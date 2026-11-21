"use client";

import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "cn";
import type { ComponentProps } from "react";

type GradientButtonProps = ComponentProps<typeof ButtonPrimitive> & {
  className?: string;
  glow?: boolean;
};

export function GradientButton({
  className,
  glow = true,
  children,
  disabled,
  ...props
}: GradientButtonProps) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      whileHover={disabled || reduceMotion ? undefined : { scale: 1.02 }}
      whileTap={disabled || reduceMotion ? undefined : { scale: 0.98 }}
      className="inline-flex"
    >
      <ButtonPrimitive
        disabled={disabled}
        className={cn(
          "gradient-primary inline-flex h-9 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium text-white shadow-lg transition-[filter,box-shadow] outline-none",
          "hover:brightness-110 focus-visible:ring-3 focus-visible:ring-violet/40",
          "disabled:pointer-events-none disabled:opacity-50",
          glow && "glow-violet",
          className,
        )}
        {...props}
      >
        {children}
      </ButtonPrimitive>
    </motion.div>
  );
}
