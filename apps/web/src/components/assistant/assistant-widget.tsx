"use client";

import { MessageCircle, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  createAssistantThread,
  getAssistantStatus,
  getAssistantThread,
  postAssistantMessage,
  type AssistantDraft,
  type AssistantMessage,
  type AssistantStatus,
} from "@/lib/api/assistant";
import { guessBrowserTimezone } from "@/lib/timezone";

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
  const bottomRef = useRef<HTMLDivElement | null>(null);

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
    if (!open) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, draft, open]);

  async function ensureThread(): Promise<string> {
    if (threadId) return threadId;
    const thread = await createAssistantThread({ timezone });
    setThreadId(thread.id);
    setMessages(thread.messages);
    setDraft(thread.draft);
    setDraftText(thread.draft?.content ?? "");
    setQuestions(thread.clarificationQuestions);
    return thread.id;
  }

  async function handleNewConversation() {
    setError(null);
    setBusy(true);
    try {
      const thread = await createAssistantThread({ timezone });
      setThreadId(thread.id);
      setMessages([]);
      setDraft(null);
      setDraftText("");
      setQuestions([]);
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
    try {
      const id = await ensureThread();
      const optimistic: AssistantMessage = {
        id: `local-${Date.now()}`,
        role: "user",
        content: text,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);
      const turn = await postAssistantMessage(id, { content: text, timezone });
      const refreshed = await getAssistantThread(id);
      setMessages(refreshed.messages);
      setQuestions(turn.clarificationQuestions);
      setDraft(turn.draft);
      setDraftText(turn.draft?.content ?? draftText);
      if (turn.state === "unavailable" || turn.state === "error") {
        setError(turn.assistantMessage?.content ?? "Assistant turn failed.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send message.");
    } finally {
      setBusy(false);
    }
  }

  if (!statusLoaded || signedOut) {
    return null;
  }

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
          className="fixed inset-0 z-40 flex flex-col bg-background sm:inset-auto sm:bottom-5 sm:right-5 sm:h-[min(640px,calc(100svh-2.5rem))] sm:w-[min(420px,calc(100vw-2.5rem))] sm:rounded-xl sm:border sm:shadow-xl"
          aria-label="AI content assistant"
        >
          <header className="flex items-center justify-between border-b px-4 py-3">
            <div>
              <p className="text-sm font-semibold">AI content assistant</p>
              <p className="text-xs text-muted-foreground">Drafts only — never auto-schedules</p>
            </div>
            <div className="flex items-center gap-2">
              <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void handleNewConversation()}>
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
              {busy ? "Thinking…" : "Send"}
            </Button>
          </form>
        </section>
      ) : null}
    </>
  );
}
