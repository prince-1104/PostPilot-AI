"use client";

import { Copy, MessageCircle, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

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
  requirements: "Gathering details",
  awaiting_user: "Waiting for your answers",
  writing: "Writing draft",
  reviewing: "Reviewing draft",
  revising: "Revising draft",
  validating: "Validating draft",
  draft_ready: "Draft ready",
  error: "Needs attention",
  generating: "Working",
};

function newClientMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function AssistantWidget() {
  const [open, setOpen] = useState(false);
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
    if (!open || hydratedRef.current || signedOut) return;
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
  }, [open, signedOut]);

  useEffect(() => {
    if (!open) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, draft, open, stage, preview, scheduledPost]);

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
    if (turn.state === "unavailable" || turn.state === "error") {
      setError(turn.assistantMessage?.content ?? "Assistant turn failed.");
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

  if (!statusLoaded || signedOut) {
    return null;
  }

  const stageLabel = stage ? STAGE_LABELS[stage] ?? stage.replaceAll("_", " ") : null;

  return (
    <>
      {!open ? (
        <button
          type="button"
          className="fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Open AI assistant"
          onClick={() => setOpen(true)}
        >
          <MessageCircle className="h-5 w-5" aria-hidden />
        </button>
      ) : null}

      {open ? (
        <section
          className="fixed inset-0 z-40 flex flex-col bg-background sm:inset-auto sm:bottom-5 sm:right-5 sm:h-[min(680px,calc(100svh-2.5rem))] sm:w-[min(440px,calc(100vw-2.5rem))] sm:rounded-xl sm:border sm:shadow-xl"
          aria-label="AI content assistant"
        >
          <header className="flex items-center justify-between border-b px-4 py-3">
            <div>
              <p className="text-sm font-semibold">AI content assistant</p>
              <p className="text-xs text-muted-foreground">
                {stageLabel ? `Stage: ${stageLabel}` : "Drafts only — never auto-schedules"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => void handleNewConversation()}
              >
                New
              </Button>
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                aria-label="Close assistant"
                onClick={() => setOpen(false)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </header>

          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
            {status && !status.aiReady ? (
              <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                {status.message}
              </p>
            ) : null}

            {messages.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Describe the LinkedIn post you want. Example: “Post a job requirement for AI Engineer
                at 7 PM.”
              </p>
            ) : null}

            {messages.map((message) => (
              <div
                key={message.id}
                className={
                  message.role === "user"
                    ? "ml-8 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                    : "mr-8 rounded-lg border border-border bg-card px-3 py-2 text-sm"
                }
              >
                <p className="whitespace-pre-wrap">{message.content}</p>
              </div>
            ))}

            {busy && stageLabel ? (
              <p className="text-xs text-muted-foreground" aria-live="polite">
                {stageLabel}…
              </p>
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

            {reviewIssues.length > 0 || validationErrors.length > 0 ? (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm">
                <p className="mb-1 font-medium">Review notes</p>
                <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                  {[...reviewIssues, ...validationErrors].slice(0, 6).map((item) => (
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
              <div className="rounded-lg border border-border bg-muted/30 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {draft.label}
                  </p>
                  <span className="text-xs text-muted-foreground">v{draft.version}</span>
                </div>
                <textarea
                  className="min-h-32 w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}
            <div ref={bottomRef} />
          </div>

          <form onSubmit={(event) => void handleSubmit(event)} className="border-t p-3">
            <label htmlFor="assistant-input" className="sr-only">
              Message
            </label>
            <textarea
              id="assistant-input"
              className="mb-2 min-h-16 w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={input}
              maxLength={4000}
              placeholder="Ask for a LinkedIn draft…"
              disabled={busy}
              onChange={(event) => setInput(event.target.value)}
            />
            <Button type="submit" className="w-full" disabled={busy || input.trim().length === 0}>
              {busy ? "Working…" : "Send"}
            </Button>
          </form>
        </section>
      ) : null}
    </>
  );
}
