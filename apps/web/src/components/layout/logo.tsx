import { cn } from "cn";

interface LogoProps {
  collapsed?: boolean;
  className?: string;
}

export function Logo({ collapsed = false, className }: LogoProps) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <span
        className="gradient-ai flex size-8 shrink-0 items-center justify-center rounded-xl text-xs font-bold tracking-tight text-white shadow-[0_0_24px_-6px_rgb(139_92_246_/_0.7)]"
        aria-hidden
      >
        PP
      </span>
      {!collapsed ? (
        <span className="font-heading text-[0.95rem] font-semibold tracking-tight">
          PostPilot
          <span className="ml-1 bg-gradient-to-r from-violet-light to-cyan bg-clip-text font-medium text-transparent">
            AI
          </span>
        </span>
      ) : (
        <span className="sr-only">PostPilot AI</span>
      )}
    </span>
  );
}
