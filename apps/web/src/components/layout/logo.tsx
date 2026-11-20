import { Send } from "lucide-react";

export function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <span className="flex size-8 items-center justify-center rounded-lg bg-brand text-brand-foreground shadow-sm">
        <Send className="size-4" aria-hidden="true" />
      </span>
      <span className="font-heading text-[0.95rem] font-semibold tracking-tight">
        PostPilot <span className="font-medium text-muted-foreground">AI</span>
      </span>
    </span>
  );
}
