"use client";

import { Bot, Copy, RefreshCw, Send, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  confirmAssistantSchedule,
  createAssistantThread,
  getAssistantStatus,
  getAssistantThread,
  listAssistantThreads,
  patchAssistantDraft,
  postAssistantMessage,
  previewAssistantSchedule,
  runAssistantDraftAction,
  type AssistantDraft,
  type AssistantMessage,
  type AssistantSchedulePreview,
  type AssistantStatus,
  type WritingStyle,
} from "@/lib/api/assistant";
import { getLinkedInConnection } from "@/lib/api/connections";
import { getPost, newIdempotencyKey, type ScheduledPost } from "@/lib/api/posts";
import {
  guessBrowserTimezone,
  instantToWallLocalInput,
  wallTimeToOffsetAwareIso,
} from "@/lib/timezone";

const TONES: WritingStyle[] = [
  "professional",
  "conversational",
  "concise",
  "detailed",
  "promotional",
];

const STAGE_LABELS: Record<string, string> = {
  intent: "Understanding request",
  requirements: "Understanding request",
  awaiting_user: "Waiting for your answers",
  writing: "Writing draft",
  reviewing: "Reviewing content",
  revising: "Reviewing content",
  validating: "Ready for approval",
  draft_ready: "Ready for approval",
  error: "Needs attention",
  generating: "Understanding request",
};

export interface AssistantWidgetProps {
  variant?: "floating" | "studio";
  /** When set, load this thread (studio thread picker). */
  threadIdOverride?: string | null;
  className?: string;
}

function newClientMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function AssistantWidget({
  variant = "floating",
  threadIdOverride,
  className,
}: AssistantWidgetProps = {}) {
  const pathname = usePathname();
  const reduceMotion = useReducedMotion();
  const isStudio = variant === "studio";
  const [open, setOpen] = useState(isStudio);
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [draft, setDraft] = useState<AssistantDraft | null>(null);
  const [questions, setQuestions] = useState<string[]>([]);
  const [draftText, setDraftText] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [tone, setTone] = useState<WritingStyle>("professional");
  const [reviewIssues, setReviewIssues] = useState<string[]>([]);
  const [reviewSuggestions, setReviewSuggestions] = useState<string[]>([]);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [lockVersion, setLockVersion] = useState(0);
  const [copied, setCopied] = useState(false);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [connectionLabel, setConnectionLabel] = useState<string | null>(null);
  const [scheduleLocal, setScheduleLocal] = useState("");
  const [ackWarnings, setAckWarnings] = useState(false);
  const [preview, setPreview] = useState<AssistantSchedulePreview | null>(null);
  const [scheduledPost, setScheduledPost] = useState<ScheduledPost | null>(null);
  const [scheduleIdempotencyKey, setScheduleIdempotencyKey] = useState(() => newIdempotencyKey());
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const hydratedRef = useRef(false);
  const pollRef = useRef<number | null>(null);

  const timezone = guessBrowserTimezone();

  useEffect(() => {
    const controller = new AbortController();
    void getAssistantStatus(controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setStatus(next);
        setSignedOut(false);
        setStatusLoaded(true);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setSignedOut(true);
          setStatus(null);
          setStatusLoaded(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Could not load assistant status.");
        setStatusLoaded(true);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!(isStudio || open) || signedOut) return;
    if (threadIdOverride) {
      const controller = new AbortController();
      void getAssistantThread(threadIdOverride, controller.signal)
        .then((detail) => {
          if (controller.signal.aborted) return;
          applyThread(detail);
          hydratedRef.current = true;
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setError(err instanceof Error ? err.message : "Could not load conversation.");
        });
      return () => controller.abort();
    }
    if (hydratedRef.current) return;
    const controller = new AbortController();
    void listAssistantThreads(controller.signal)
      .then(async (threads) => {
        if (controller.signal.aborted || threads.length === 0) {
          hydratedRef.current = true;
          return;
        }
        const latest = threads[0];
        if (!latest) {
          hydratedRef.current = true;
          return;
        }
        const detail = await getAssistantThread(latest.id, controller.signal);
        if (controller.signal.aborted) return;
        applyThread(detail);
        hydratedRef.current = true;
      })
      .catch(() => {
        hydratedRef.current = true;
      });
    return () => controller.abort();
  }, [open, signedOut, threadIdOverride, isStudio]);

  // Scroll only the chat panel — never the page (scrollIntoView was jumping the window).
  useEffect(() => {
    if (!(isStudio || open)) return;
    const panel = scrollRef.current;
    if (!panel) return;
    panel.scrollTo({
      top: panel.scrollHeight,
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [messages, busy, open, isStudio, reduceMotion]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void getLinkedInConnection(controller.signal)
      .then((conn) => {
        if (controller.signal.aborted) return;
        setConnectionId(conn.id);
        setConnectionLabel(conn.displayName ?? conn.personUrn ?? "LinkedIn account");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setConnectionId(null);
      });
    return () => controller.abort();
  }, [open]);

  useEffect(() => {
    if (!scheduledPost?.id) return;
    const terminal = new Set(["published", "failed", "cancelled", "requires_review"]);
    if (terminal.has(scheduledPost.status)) return;

    const tick = () => {
      void getPost(scheduledPost.id)
        .then((next) => setScheduledPost(next))
        .catch(() => undefined);
    };
    pollRef.current = window.setInterval(tick, 4000);
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [scheduledPost?.id, scheduledPost?.status]);

  function applyThread(detail: {
    id: string;
    messages: AssistantMessage[];
    draft: AssistantDraft | null;
    clarificationQuestions: string[];
    currentStage: string | null;
    writingStyle: WritingStyle | null;
    reviewIssues: string[];
    reviewSuggestions: string[];
    validationErrors: string[];
    lockVersion: number;
  }) {
    setThreadId(detail.id);
    setMessages(detail.messages);
    setDraft(detail.draft);
    setDraftText(detail.draft?.content ?? "");
    setQuestions(detail.clarificationQuestions);
    setStage(detail.currentStage);
    if (detail.writingStyle) setTone(detail.writingStyle);
    setReviewIssues(detail.reviewIssues);
    setReviewSuggestions(detail.reviewSuggestions);
    setValidationErrors(detail.validationErrors);
    setLockVersion(detail.lockVersion);
    if (detail.draft?.proposedScheduledAt && detail.draft.timezone) {
      setScheduleLocal(
        instantToWallLocalInput(detail.draft.proposedScheduledAt, detail.draft.timezone),
      );
    }
    if (detail.draft?.scheduledPostId) {
      void getPost(detail.draft.scheduledPostId)
        .then((post) => setScheduledPost(post))
        .catch(() => undefined);
    }
  }

  function applyTurn(turn: {
    currentStage: string | null;
    clarificationQuestions: string[];
    draft: AssistantDraft | null;
    writingStyle: WritingStyle | null;
    reviewIssues: string[];
    reviewSuggestions: string[];
    validationErrors: string[];
    lockVersion: number;
    state: string;
    assistantMessage: AssistantMessage | null;
  }) {
    setStage(turn.currentStage);
    setQuestions(turn.clarificationQuestions);
    setDraft(turn.draft);
    if (turn.draft) setDraftText(turn.draft.content);
    if (turn.writingStyle) setTone(turn.writingStyle);
    setReviewIssues(turn.reviewIssues);
    setReviewSuggestions(turn.reviewSuggestions);
    setValidationErrors(turn.validationErrors);
    setLockVersion(turn.lockVersion);
    if (turn.draft?.proposedScheduledAt && turn.draft.timezone) {
      setScheduleLocal(
        instantToWallLocalInput(turn.draft.proposedScheduledAt, turn.draft.timezone),
      );
    }
    if (turn.state === "unavailable") {
      setError(turn.assistantMessage?.content ?? "Assistant is unavailable.");
    } else if (turn.state === "error") {
      // Refusal/error text already appears in the message list — avoid duplicating it.
      setError(null);
    } else {
      setError(null);
    }
  }

  async function ensureThread(): Promise<string> {
    if (threadId) return threadId;
    const thread = await createAssistantThread({ timezone });
    applyThread(thread);
    return thread.id;
  }

  async function handleNewConversation() {
    setError(null);
    setBusy(true);
    try {
      const thread = await createAssistantThread({ timezone });
      applyThread(thread);
      setMessages([]);
      setDraft(null);
      setDraftText("");
      setQuestions([]);
      setReviewIssues([]);
      setReviewSuggestions([]);
      setValidationErrors([]);
      setStage(null);
      setInput("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start a conversation.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setInput("");
    setStage("generating");
    try {
      const id = await ensureThread();
      const optimistic: AssistantMessage = {
        id: `local-${Date.now()}`,
        role: "user",
        content: text,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);
      const turn = await postAssistantMessage(id, {
        content: text,
        timezone,
        tone,
        clientMessageId: newClientMessageId(),
      });
      const refreshed = await getAssistantThread(id);
      setMessages(refreshed.messages);
      applyTurn(turn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send message.");
      setStage("error");
    } finally {
      setBusy(false);
    }
  }

  async function handleDraftAction(action: "regenerate" | "rewrite" | "set_tone", instruction?: string) {
    if (!threadId || busy) return;
    setBusy(true);
    setError(null);
    setStage(action === "regenerate" ? "writing" : "revising");
    try {
      const turn = await runAssistantDraftAction(threadId, {
        action,
        instruction,
        tone: action === "set_tone" ? tone : undefined,
        expectedVersion: draft?.version,
        clientMessageId: newClientMessageId(),
      });
      const refreshed = await getAssistantThread(threadId);
      setMessages(refreshed.messages);
      applyTurn(turn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update draft.");
      setStage("error");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveDraft() {
    if (!threadId || !draft || busy) return;
    if (draftText.trim() === draft.content) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await patchAssistantDraft(threadId, {
        content: draftText.trim(),
        expectedVersion: draft.version,
        expectedLockVersion: lockVersion,
      });
      setDraft(updated);
      setDraftText(updated.content);
      setLockVersion((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save draft edits.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy() {
    const text = draftText || draft?.content || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Could not copy draft to clipboard.");
    }
  }

  async function handleSchedulePreview() {
    if (!draft || !connectionId || !scheduleLocal || busy) return;
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      const scheduledAt = wallTimeToOffsetAwareIso(scheduleLocal, timezone);
      const next = await previewAssistantSchedule(draft.id, {
        expectedDraftVersion: draft.version,
        content: draftText.trim(),
        linkedinConnectionId: connectionId,
        scheduledAt,
        timezone,
        acknowledgeWarnings: ackWarnings,
      });
      setPreview(next);
      if (!next.canConfirm && next.hardBlockers.length > 0) {
        setError(next.hardBlockers[0] ?? "Cannot schedule this draft yet.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Schedule preview failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleApproveAndSchedule() {
    if (!draft || !connectionId || !scheduleLocal || busy) return;
    setBusy(true);
    setError(null);
    try {
      const scheduledAt = wallTimeToOffsetAwareIso(scheduleLocal, timezone);
      const result = await confirmAssistantSchedule(
        draft.id,
        {
          expectedDraftVersion: draft.version,
          content: draftText.trim(),
          linkedinConnectionId: connectionId,
          scheduledAt,
          timezone,
          acknowledgeWarnings: ackWarnings,
        },
        scheduleIdempotencyKey,
      );
      setScheduledPost(result.post);
      setDraft({
        ...draft,
        scheduledPostId: result.scheduledPostId,
        status: "scheduled",
        label: "Scheduled",
      });
      setPreview(null);
      setScheduleIdempotencyKey(newIdempotencyKey());
      if (threadId) {
        const refreshed = await getAssistantThread(threadId);
        setMessages(refreshed.messages);
        if (refreshed.draft) {
          setDraft(refreshed.draft);
          setDraftText(refreshed.draft.content);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve and schedule.");
    } finally {
      setBusy(false);
    }
  }

  if (!isStudio && pathname.startsWith("/assistant")) {
    return null;
  }

  if (!statusLoaded) {
    return null;
  }

  if (signedOut) {
    if (isStudio) {
      return (
        <div className={cn("flex h-full items-center justify-center p-8", className)}>
          <p className="text-sm text-muted-foreground">
            Sign in on Connections to use AI Studio.
          </p>
        </div>
      );
    }
    return null;
  }

  const stageLabel = stage ? STAGE_LABELS[stage] ?? stage.replaceAll("_", " ") : null;
  const panelOpen = isStudio || open;
  const inputId = isStudio ? "assistant-studio-input" : "assistant-widget-input";

  return (
    <>
      <AnimatePresence>
        {!isStudio && !open ? (
          <motion.div
            key="agent-launcher"
            className="fixed right-5 bottom-5 z-40"
            initial={reduceMotion ? false : { scale: 0.7, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={reduceMotion ? undefined : { scale: 0.8, opacity: 0 }}
            transition={{ duration: 0.22 }}
          >
            <button
              type="button"
              className="group relative flex size-16 items-center justify-center rounded-full focus-visible:ring-3 focus-visible:ring-violet/50 focus-visible:outline-none"
              aria-label="Open AI chat agent"
              onClick={() => setOpen(true)}
            >
              <span
                className="agent-ring pointer-events-none absolute inset-[-6px] rounded-full border border-violet/40 border-t-cyan/70 border-r-transparent"
                aria-hidden
              />
              <span
                className="agent-ring-delay pointer-events-none absolute inset-[-12px] rounded-full border border-cyan/25 border-b-violet/50 border-l-transparent opacity-70"
                aria-hidden
              />
              <span
                className={cn(
                  "gradient-ai relative flex size-14 items-center justify-center rounded-full text-white",
                  !reduceMotion && "agent-orb-glow",
                )}
              >
                <Bot className="size-6 drop-shadow-[0_0_8px_rgb(255_255_255_/_0.55)]" aria-hidden />
                <span
                  className="agent-status-dot absolute right-1 bottom-1 size-2.5 rounded-full bg-cyan ring-2 ring-[#0d1220]"
                  aria-hidden
                />
              </span>
              <span className="pointer-events-none absolute -top-9 right-0 rounded-full border border-violet/30 bg-background-elevated/95 px-2.5 py-1 text-[11px] font-medium text-violet-light opacity-0 shadow-lg backdrop-blur-md transition-opacity group-hover:opacity-100">
                Chat agent
              </span>
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {panelOpen ? (
          <motion.section
            key="agent-panel"
            initial={
              isStudio || reduceMotion
                ? false
                : { opacity: 0, y: 24, scale: 0.96 }
            }
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduceMotion || isStudio ? undefined : { opacity: 0, y: 16, scale: 0.97 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className={cn(
              "flex flex-col overflow-hidden border-border bg-background-elevated/95 backdrop-blur-xl",
              isStudio
                ? "h-full min-h-[70vh] rounded-2xl border shadow-xl"
                : cn(
                    "fixed inset-0 z-40 sm:inset-auto sm:right-5 sm:bottom-5",
                    "sm:h-[min(740px,calc(100svh-2.5rem))] sm:w-[min(440px,calc(100vw-2.5rem))]",
                    "sm:rounded-[1.35rem]",
                    !reduceMotion && "agent-panel-glow",
                    reduceMotion && "border shadow-2xl glow-violet",
                  ),
              className,
            )}
            aria-label="AI chat agent"
          >
            {!isStudio ? (
              <div
                className="pointer-events-none absolute inset-x-0 top-0 h-24 opacity-80"
                aria-hidden
                style={{
                  background:
                    "radial-gradient(ellipse 80% 100% at 50% 0%, rgb(139 92 246 / 0.28), transparent 70%)",
                }}
              />
            ) : null}

            <header className="relative z-10 flex items-center justify-between border-b border-border/70 px-4 py-3.5">
              <div className="flex items-center gap-3">
                <span className="relative">
                  <span className="gradient-ai flex size-10 items-center justify-center rounded-full text-white shadow-[0_0_24px_-4px_rgb(139_92_246_/_0.8)]">
                    <Bot className="size-5" aria-hidden />
                  </span>
                  <span
                    className="agent-status-dot absolute right-0 bottom-0 size-2.5 rounded-full bg-cyan ring-2 ring-background-elevated"
                    aria-hidden
                  />
                </span>
                <div>
                  <p className="text-sm font-semibold tracking-tight">PostPilot Agent</p>
                  <p className="flex items-center gap-1.5 font-meta text-cyan/90">
                    <span className="size-1.5 rounded-full bg-cyan" aria-hidden />
                    {busy && stageLabel
                      ? stageLabel
                      : stageLabel
                        ? stageLabel
                        : "Online · drafts only"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  className="border-violet/25 bg-violet/10 text-violet-light hover:bg-violet/20"
                  onClick={() => void handleNewConversation()}
                >
                  New chat
                </Button>
                {!isStudio ? (
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    aria-label="Close assistant"
                    onClick={() => setOpen(false)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            </header>

            <div
              ref={scrollRef}
              className="relative z-10 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
            >
              {status && !status.aiReady ? (
                <p className="rounded-xl border border-amber/30 bg-amber/10 px-3 py-2 text-sm text-amber">
                  {status.message}
                </p>
              ) : null}

              {messages.length === 0 ? (
                <div className="flex flex-col items-center gap-3 rounded-2xl border border-violet/20 bg-gradient-to-b from-violet/10 to-transparent px-5 py-8 text-center">
                  <span className="gradient-ai flex size-12 items-center justify-center rounded-full text-white shadow-[0_0_28px_-4px_rgb(139_92_246_/_0.7)]">
                    <Sparkles className="size-5" aria-hidden />
                  </span>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-foreground">How can I help you post?</p>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      Describe the LinkedIn post you want. Example: “Post a job requirement for AI
                      Engineer at 7 PM.”
                    </p>
                  </div>
                </div>
              ) : null}

              {messages.map((message) => {
                const isUser = message.role === "user";
                return (
                  <motion.div
                    key={message.id}
                    initial={reduceMotion ? false : { opacity: 0, y: 8, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{ duration: 0.22 }}
                    className={cn("flex gap-2.5", isUser ? "flex-row-reverse" : "flex-row")}
                  >
                    {!isUser ? (
                      <span className="gradient-ai mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full text-white shadow-[0_0_16px_-4px_rgb(139_92_246_/_0.7)]">
                        <Bot className="size-3.5" aria-hidden />
                      </span>
                    ) : null}
                    <div
                      className={cn(
                        "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                        isUser
                          ? "rounded-br-md border border-violet/40 bg-violet/25 text-foreground shadow-[0_0_20px_-8px_rgb(139_92_246_/_0.55)]"
                          : "rounded-bl-md border border-border/80 bg-surface/90 text-foreground/95",
                      )}
                    >
                      <p className="whitespace-pre-wrap">{message.content}</p>
                    </div>
                  </motion.div>
                );
              })}

              {busy ? (
                <div
                  className="flex items-center gap-2.5"
                  aria-live="polite"
                >
                  <span className="gradient-ai flex size-7 shrink-0 items-center justify-center rounded-full text-white">
                    <Bot className="size-3.5" aria-hidden />
                  </span>
                  <div className="rounded-2xl rounded-bl-md border border-cyan/30 bg-cyan/10 px-3.5 py-2.5">
                    <div className="mb-1 flex items-center gap-1.5">
                      <span
                        className="agent-typing-dot size-1.5 rounded-full bg-cyan"
                        style={{ animationDelay: "0ms" }}
                        aria-hidden
                      />
                      <span
                        className="agent-typing-dot size-1.5 rounded-full bg-cyan"
                        style={{ animationDelay: "160ms" }}
                        aria-hidden
                      />
                      <span
                        className="agent-typing-dot size-1.5 rounded-full bg-cyan"
                        style={{ animationDelay: "320ms" }}
                        aria-hidden
                      />
                    </div>
                    <p className="text-[11px] text-cyan">{stageLabel ?? "Working"}…</p>
                  </div>
                </div>
              ) : null}

            {questions.length > 0 ? (
              <div className="rounded-lg border border-dashed border-border px-3 py-2 text-sm">
                <p className="mb-1 font-medium">Follow-up questions</p>
                <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                  {questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {reviewIssues.length > 0 ||
            validationErrors.filter((item) => item !== "prompt_injection_blocked").length > 0 ? (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm">
                <p className="mb-1 font-medium">Review notes</p>
                <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                  {[
                    ...reviewIssues,
                    ...validationErrors.filter((item) => item !== "prompt_injection_blocked"),
                  ]
                    .slice(0, 6)
                    .map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                {reviewSuggestions.length > 0 ? (
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-muted-foreground">
                    {reviewSuggestions.slice(0, 4).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}

            {draft ? (
              <div className="rounded-2xl border border-violet/25 bg-violet/5 p-3.5">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="font-mono text-[10px] font-medium tracking-[0.14em] text-violet-light uppercase">
                    {draft.label}
                  </p>
                  <span className="font-meta">v{draft.version}</span>
                </div>
                <textarea
                  className="min-h-32 w-full resize-y rounded-xl border border-input bg-background-elevated px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-violet/40"
                  value={draftText}
                  onChange={(event) => setDraftText(event.target.value)}
                  aria-label="Editable draft content"
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    Tone
                    <select
                      className="rounded-md border border-input bg-background px-2 py-1 text-xs"
                      value={tone}
                      disabled={busy}
                      onChange={(event) => setTone(event.target.value as WritingStyle)}
                    >
                      {TONES.map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void handleDraftAction("set_tone")}
                  >
                    Apply tone
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void handleDraftAction("rewrite", "Make it shorter and more professional.")
                    }
                  >
                    Rewrite shorter
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void handleDraftAction("regenerate")}
                  >
                    <RefreshCw className="mr-1 h-3.5 w-3.5" />
                    Regenerate
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void handleCopy()}
                  >
                    <Copy className="mr-1 h-3.5 w-3.5" />
                    {copied ? "Copied" : "Copy"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={busy || draftText.trim() === draft.content}
                    onClick={() => void handleSaveDraft()}
                  >
                    Save edits
                  </Button>
                </div>

                {draft.scheduledPostId ? (
                  <div className="mt-3 rounded-md border border-border bg-background px-3 py-2 text-sm">
                    <p className="font-medium">Linked scheduled post</p>
                    <p className="text-xs text-muted-foreground">{draft.scheduledPostId}</p>
                    <Button
                      type="button"
                      size="sm"
                      className="mt-2"
                      render={<Link href={`/posts/${draft.scheduledPostId}`} />}
                    >
                      View scheduled post
                    </Button>
                    {scheduledPost ? (
                      <p className="mt-2 text-xs text-muted-foreground">
                        Status: {scheduledPost.status}
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <div className="mt-3 space-y-2 rounded-md border border-dashed border-border p-3">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Approve &amp; Schedule
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Chat messages never schedule. Confirm destination and time explicitly.
                    </p>
                    <label className="block text-xs text-muted-foreground">
                      LinkedIn account
                      <input
                        className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
                        value={connectionLabel ?? (connectionId ? connectionId : "Not connected")}
                        readOnly
                        aria-readonly
                      />
                    </label>
                    <label className="block text-xs text-muted-foreground">
                      Schedule (local wall time)
                      <input
                        type="datetime-local"
                        className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
                        value={scheduleLocal}
                        disabled={busy}
                        onChange={(event) => setScheduleLocal(event.target.value)}
                      />
                    </label>
                    <p className="text-xs text-muted-foreground">Timezone: {timezone}</p>
                    {(reviewIssues.length > 0 || (preview?.advisoryWarnings.length ?? 0) > 0) && (
                      <label className="flex items-start gap-2 text-xs text-muted-foreground">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={ackWarnings}
                          disabled={busy}
                          onChange={(event) => setAckWarnings(event.target.checked)}
                        />
                        I reviewed advisory warnings and want to proceed.
                      </label>
                    )}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy || !connectionId || !scheduleLocal}
                        onClick={() => void handleSchedulePreview()}
                      >
                        Preview schedule
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy || !preview?.canConfirm || !connectionId}
                        onClick={() => void handleApproveAndSchedule()}
                      >
                        Approve &amp; Schedule
                      </Button>
                    </div>
                    {preview ? (
                      <div className="rounded-md bg-muted/40 px-2 py-2 text-xs">
                        <p>
                          <span className="font-medium">When: </span>
                          {preview.scheduledAtLocal} ({preview.timezone})
                        </p>
                        <p>
                          <span className="font-medium">UTC: </span>
                          {preview.scheduledAtUtc}
                        </p>
                        {preview.hardBlockers.length > 0 ? (
                          <ul className="mt-1 list-disc pl-4 text-destructive">
                            {preview.hardBlockers.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        ) : null}
                        {preview.advisoryWarnings.length > 0 ? (
                          <ul className="mt-1 list-disc pl-4 text-muted-foreground">
                            {preview.advisoryWarnings.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ) : null}

            {error ? (
              <p className="text-sm text-rose" role="alert">
                {error}
              </p>
            ) : null}
            <div ref={bottomRef} />
          </div>

          <form
            onSubmit={(event) => void handleSubmit(event)}
            className="relative z-10 border-t border-border/70 bg-background/40 p-3 backdrop-blur-md"
          >
            <label htmlFor={inputId} className="sr-only">
              Message
            </label>
            <div className="flex items-end gap-2 rounded-2xl border border-violet/25 bg-surface/60 p-2 shadow-[inset_0_0_24px_-12px_rgb(139_92_246_/_0.35)] focus-within:border-violet/50 focus-within:shadow-[0_0_24px_-8px_rgb(139_92_246_/_0.45)]">
              <textarea
                id={inputId}
                className="max-h-32 min-h-11 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-muted-foreground"
                value={input}
                maxLength={4000}
                rows={2}
                placeholder="Message the agent…"
                disabled={busy}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
              />
              <Button
                type="submit"
                size="icon"
                className="gradient-ai size-10 shrink-0 rounded-xl border-0 text-white shadow-[0_0_20px_-4px_rgb(139_92_246_/_0.7)]"
                disabled={busy || input.trim().length === 0}
                aria-label={busy ? "Working" : "Send message"}
              >
                <Send className="size-4" aria-hidden />
              </Button>
            </div>
            <p className="mt-2 text-center font-meta text-[10px] text-muted-foreground/80">
              Enter to send · Shift+Enter for new line · never auto-schedules
            </p>
          </form>
          </motion.section>
        ) : null}
      </AnimatePresence>
    </>
  );
}
