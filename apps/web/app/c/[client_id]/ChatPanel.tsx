"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { BrandingData } from "./types";

type Part =
  | { kind: "text"; text: string }
  | { kind: "cite"; index: number; source: string; title: string; cited_text: string };

interface TurnMeta {
  cost_usd: number;
  latency_ms: number;
  cache_read_input_tokens: number;
  escalated?: boolean;
  confidence?: number;
  ticket_id?: string | null;
}

// One completed pipeline stage. Emitted by the `step` SSE event and rendered as an
// audit trail beside the answer — the same data the backend commits to Run.steps, so
// what the user watches and what is recorded cannot drift.
export interface RunStep {
  seq: number;
  stage: string;
  status: string;
  reasoning?: string | null;
  latency_ms?: number;
  confidence?: number;
  n_hits?: number;
  top_similarity?: number;
  n_citations?: number;
  ticket_id?: string;
  cost_usd?: number;
}

type ChatMessage =
  | { role: "user"; text: string }
  | { role: "assistant"; parts: Part[]; meta?: TurnMeta; error?: string; steps?: RunStep[] };

interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  let idx: number;
  while ((idx = buffer.indexOf("\n\n")) !== -1) {
    const frame = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length > 0) {
      try {
        events.push({ event, data: JSON.parse(dataLines.join("\n")) });
      } catch {
        // drop malformed frames
      }
    }
  }
  return { events, rest: buffer };
}

function toolLabel(name: string): string {
  if (name === "search_docs") return "Searching documents";
  if (name === "get_document") return "Opening document";
  return `Running ${name}`;
}

const POPOVER_W = 384; // w-96

function storageKey(clientId: string): string {
  return `configent:conv:${clientId}`;
}

interface HistorySegment {
  text: string;
  citations: { source: string; title: string; cited_text: string }[];
}

// Map stored citation segments (backend shape) into the Part[] shape the
// renderer already understands, with sequential per-message citation indices
// (mirrors the per-turn `citation_index` counter used while streaming live).
function segmentsToParts(segments: HistorySegment[]): Part[] {
  const parts: Part[] = [];
  let index = 0;
  for (const seg of segments) {
    if (seg.text) parts.push({ kind: "text", text: seg.text });
    for (const cite of seg.citations ?? []) {
      index += 1;
      parts.push({
        kind: "cite",
        index,
        source: cite.source ?? "",
        title: cite.title ?? "Source",
        cited_text: cite.cited_text ?? "",
      });
    }
  }
  return parts;
}

interface HistoryMessage {
  role: "user" | "assistant";
  text?: string;
  segments?: HistorySegment[];
}

function historyToMessages(history: HistoryMessage[]): ChatMessage[] {
  return history.map((m) =>
    m.role === "user"
      ? { role: "user", text: m.text ?? "" }
      : { role: "assistant", parts: segmentsToParts(m.segments ?? []) }
  );
}

// Strip markdown syntax from cited_text so it reads as plain prose in the popover
function stripMd(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/^[-*]{3,}$/gm, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

type CitePart = Extract<Part, { kind: "cite" }>;

// Group consecutive text parts with the citations that immediately follow them
// so citations render inline after their source paragraph, not as orphaned blocks.
//
// A group may only end at a markdown *block* boundary. The API returns one text block
// per cited span, so a cited numbered list arrives as "1. " / cite / "item text. 2. " /
// cite / ... — splitting on every citation would render each fragment as its own
// markdown document and the list collapses into broken single-item lists. Citations
// that land mid-block are held and rendered after the block completes.
function endsBlock(text: string): boolean {
  return /\n[ \t]*\n[ \t]*$/.test(text);
}

function groupParts(parts: Part[]): { text: string; cites: CitePart[] }[] {
  const groups: { text: string; cites: CitePart[] }[] = [];
  let cur = { text: "", cites: [] as CitePart[] };
  for (const part of parts) {
    if (part.kind === "text") {
      const boundary = endsBlock(cur.text) || /^[ \t]*\n[ \t]*\n/.test(part.text);
      if (cur.cites.length > 0 && boundary) {
        groups.push(cur);
        cur = { text: "", cites: [] };
      }
      cur.text += part.text;
    } else {
      cur.cites.push(part);
    }
  }
  if (cur.text || cur.cites.length > 0) groups.push(cur);
  return groups;
}

function CitationPopover({ part, color }: { part: CitePart; color: string }) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<React.CSSProperties>({});
  const wrapRef = useRef<HTMLSpanElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  function handleToggle() {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const left = Math.max(8, Math.min(r.left + r.width / 2 - POPOVER_W / 2, window.innerWidth - POPOVER_W - 8));
      // Open below if button is in top half of viewport, above otherwise
      const showBelow = r.top < window.innerHeight / 2;
      setStyle(showBelow
        ? { position: "fixed", top: r.bottom + 8, left, zIndex: 50 }
        : { position: "fixed", top: r.top - 8, left, transform: "translateY(-100%)", zIndex: 50 }
      );
    }
    setOpen((v) => !v);
  }

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    function onDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const cleanText = (() => {
    const s = stripMd(part.cited_text);
    if (s.length <= 300) return s;
    const cut = s.slice(0, 300);
    const lastStop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf(".\n"));
    return lastStop > 100 ? cut.slice(0, lastStop + 1) : cut.trimEnd() + "…";
  })();

  return (
    <span ref={wrapRef} className="inline-block">
      <button
        ref={btnRef}
        onClick={handleToggle}
        className="inline-flex items-center justify-center w-4 h-4 rounded text-[10px] font-bold cursor-pointer transition-colors mx-0.5 align-middle"
        style={{
          backgroundColor: open ? color : undefined,
          color: open ? "#fff" : color,
          border: `1px solid ${color}`,
        }}
        aria-label={`Citation ${part.index}: ${part.title}`}
      >
        {part.index}
      </button>
      {open && (
        <span
          className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-white/10 rounded-xl shadow-2xl text-left overflow-hidden"
          style={{ ...style, width: POPOVER_W }}
        >
          {/* Header */}
          <span className="flex items-start gap-2 px-4 pt-4 pb-3 border-b border-gray-100 dark:border-white/10">
            <svg className="w-3.5 h-3.5 shrink-0 mt-0.5 text-gray-400 dark:text-white/30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span className="text-xs font-semibold text-gray-900 dark:text-white leading-snug break-words">{part.title}</span>
          </span>
          {/* Excerpt */}
          <span className="block px-4 py-3">
            <span className="block text-xs text-gray-500 dark:text-white/50 leading-relaxed break-words italic">
              "{cleanText}"
            </span>
          </span>
          {/* Source */}
          <span className="flex items-center gap-1.5 px-4 pb-3 text-[11px] text-gray-400 dark:text-white/30">
            <span className="truncate">{part.source}</span>
          </span>
        </span>
      )}
    </span>
  );
}

function TypingDots({ color }: { color: string }) {
  return (
    <span className="inline-flex items-end gap-0.5 h-4">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1 h-1 rounded-full animate-bounce"
          style={{ backgroundColor: color, animationDelay: `${i * 120}ms` }}
        />
      ))}
    </span>
  );
}

// ── Pipeline audit trail ──────────────────────────────────────────────────────────
// Every stage the agent ran, with the reasoning it recorded at the time. This is the
// deliverable, not decoration: it shows *why* a question was answered or escalated,
// which is the thing an escalation decision has to be able to justify.

const STAGE_LABEL: Record<string, string> = {
  retrieve: "Searched the documentation",
  score: "Scored the evidence",
  answer: "Answered from sources",
  escalate: "Escalated to a human",
  ticket: "Filed a ticket",
};

function stageDetail(step: RunStep): string | null {
  switch (step.stage) {
    case "retrieve":
      return step.n_hits === 0
        ? "no matching passages"
        : `${step.n_hits} passage${step.n_hits === 1 ? "" : "s"} · best match ${step.top_similarity?.toFixed(2)}`;
    case "score":
      return step.confidence !== undefined ? `confidence ${step.confidence.toFixed(2)}` : null;
    case "answer":
      return step.n_citations !== undefined ? `${step.n_citations} citations` : null;
    case "ticket":
      return step.ticket_id ?? null;
    default:
      return null;
  }
}

function StepTrail({ steps, live }: { steps: RunStep[]; live: boolean }) {
  const [open, setOpen] = useState(live);
  if (steps.length === 0) return null;
  const escalated = steps.some((s) => s.stage === "escalate");

  return (
    <div className="mb-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-gray-400 dark:text-white/40 hover:text-gray-600 dark:hover:text-white/70 transition-colors"
        aria-expanded={open}
      >
        <svg
          className={`w-3 h-3 transition-transform ${open ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span className="uppercase tracking-wide font-medium">
          {steps.length} step{steps.length === 1 ? "" : "s"}
        </span>
        {escalated && (
          <span className="ml-1 px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-500/15 text-amber-700 dark:text-amber-400 font-medium normal-case tracking-normal">
            escalated
          </span>
        )}
      </button>

      {open && (
        <ol className="mt-2 border-l border-gray-200 dark:border-white/10 pl-3 space-y-2">
          {steps.map((step) => {
            const detail = stageDetail(step);
            const failed = step.status !== "ok";
            return (
              <li key={step.seq} className="relative">
                <span
                  className={`absolute -left-[17px] top-1.5 w-1.5 h-1.5 rounded-full ${
                    failed
                      ? "bg-red-500"
                      : step.stage === "escalate" || step.stage === "ticket"
                        ? "bg-amber-500"
                        : "bg-gray-300 dark:bg-white/25"
                  }`}
                  aria-hidden="true"
                />
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-gray-600 dark:text-white/60 font-medium">
                    {STAGE_LABEL[step.stage] ?? step.stage}
                  </span>
                  {detail && (
                    <span className="text-gray-400 dark:text-white/35 tabular-nums">{detail}</span>
                  )}
                  {step.latency_ms !== undefined && (
                    <span className="text-gray-300 dark:text-white/20 tabular-nums">
                      {step.latency_ms}ms
                    </span>
                  )}
                </div>
                {step.reasoning && (
                  <p className="mt-0.5 text-gray-400 dark:text-white/35 leading-relaxed">
                    {step.reasoning}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

export default function ChatPanel({ branding }: { branding: BrandingData }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // Steps for the turn currently streaming. Kept separate from the message so the
  // trail can be shown before the first answer token arrives; W2 also needs runId to
  // offer "Resume" when a stream closes without `done`.
  const [liveSteps, setLiveSteps] = useState<RunStep[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const suggestions = branding.suggested_questions ?? [];

  // On mount, try to resume a conversation stored for this client. A 404
  // (nightly reset, or the id belongs to a client that no longer matches)
  // clears the stored id and starts fresh instead of surfacing an error.
  useEffect(() => {
    const storedId = sessionStorage.getItem(storageKey(branding.id));
    if (!storedId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/c/${branding.id}/conversations/${storedId}`);
        if (!res.ok) {
          sessionStorage.removeItem(storageKey(branding.id));
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        setConversationId(storedId);
        setMessages(historyToMessages(data.messages ?? []));
      } catch {
        // Network hiccup: leave the stored id in place and just start fresh
        // for this load; the user can still resume on a later visit.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [branding.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolStatus]);

  function startNewChat() {
    sessionStorage.removeItem(storageKey(branding.id));
    setConversationId(null);
    setMessages([]);
    setInput("");
  }

  function updateLastAssistant(fn: (msg: Extract<ChatMessage, { role: "assistant" }>) => void) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role !== "assistant") return prev;
      const copy = { ...last, parts: [...last.parts] };
      fn(copy);
      next[next.length - 1] = copy;
      return next;
    });
  }

  function handleEvent(event: string, data: Record<string, unknown>) {
    if (event === "text") {
      setToolStatus(null);
      updateLastAssistant((msg) => {
        const lastPart = msg.parts[msg.parts.length - 1];
        if (lastPart?.kind === "text") {
          msg.parts[msg.parts.length - 1] = {
            kind: "text",
            text: lastPart.text + (data.delta as string),
          };
        } else {
          msg.parts.push({ kind: "text", text: data.delta as string });
        }
      });
    } else if (event === "citation") {
      updateLastAssistant((msg) => {
        msg.parts.push({
          kind: "cite",
          index: data.index as number,
          source: (data.source as string) ?? "",
          title: (data.title as string) ?? "Source",
          cited_text: (data.cited_text as string) ?? "",
        });
      });
    } else if (event === "tool") {
      if (data.status === "start") setToolStatus(toolLabel(data.name as string));
      else setToolStatus(null);
    } else if (event === "run") {
      setRunId(data.run_id as string);
    } else if (event === "step") {
      // Each stage of the pipeline as it completes. Shown live, then kept with the
      // message so the trail is still there after the answer finishes.
      const step = data as unknown as RunStep;
      setLiveSteps((prev) => [...prev, step]);
      setToolStatus(null);
      updateLastAssistant((msg) => {
        msg.steps = [...(msg.steps ?? []), step];
      });
    } else if (event === "done") {
      const newConversationId = data.conversation_id as string;
      setConversationId(newConversationId);
      sessionStorage.setItem(storageKey(branding.id), newConversationId);
      updateLastAssistant((msg) => {
        msg.meta = {
          cost_usd: data.cost_usd as number,
          latency_ms: data.latency_ms as number,
          cache_read_input_tokens: data.cache_read_input_tokens as number,
          escalated: data.escalated as boolean | undefined,
          confidence: data.confidence as number | undefined,
          ticket_id: (data.ticket_id as string | null) ?? null,
        };
      });
      setLiveSteps([]);
    } else if (event === "error") {
      updateLastAssistant((msg) => {
        msg.error = (data.message as string) || "Something went wrong.";
      });
    }
  }

  async function send(text?: string) {
    const question = (text ?? input).trim();
    if (!question || streaming) return;
    setInput("");
    setMessages((prev) => [
      ...prev,
      { role: "user", text: question },
      { role: "assistant", parts: [] },
    ]);
    setStreaming(true);
    try {
      const res = await fetch(`/api/c/${branding.id}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, conversation_id: conversationId }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = parseSse(buffer);
        buffer = rest;
        for (const { event, data } of events) handleEvent(event, data);
      }
    } catch {
      updateLastAssistant((msg) => {
        msg.error = "Connection lost — please try again.";
      });
    } finally {
      setStreaming(false);
      setToolStatus(null);
      inputRef.current?.focus();
    }
  }

  const lastIsEmptyAssistant =
    streaming &&
    messages[messages.length - 1]?.role === "assistant" &&
    (messages[messages.length - 1] as Extract<ChatMessage, { role: "assistant" }>).parts.length === 0;

  const isEmpty = messages.length === 0;

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full max-w-3xl mx-auto px-4">
      {!isEmpty && (
        <div className="flex justify-end pt-3 shrink-0">
          <button
            onClick={startNewChat}
            disabled={streaming}
            className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-white/40 hover:text-gray-700 dark:hover:text-white/70 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New chat
          </button>
        </div>
      )}
      {/* Messages */}
      <div className="flex-1 overflow-y-auto py-6 space-y-6 scroll-smooth">
        {/* Welcome state */}
        {isEmpty && (
          <div className="flex flex-col items-center text-center pt-10 pb-4">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center text-white text-2xl font-bold mb-4 shadow-lg"
              style={{ backgroundColor: branding.primary_color }}
            >
              {branding.assistant_name.charAt(0)}
            </div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">{branding.assistant_name}</h2>
            <p className="text-sm text-gray-500 dark:text-white/50 max-w-md mb-8 leading-relaxed">
              {branding.tagline ??
                `Ask me anything about ${branding.name} — I answer from your documents with cited sources.`}
            </p>

            {suggestions.length > 0 && (
              <div className="w-full max-w-md space-y-2">
                <p className="text-xs text-gray-400 dark:text-white/30 uppercase tracking-wide font-medium mb-3">Try asking</p>
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => void send(s)}
                    className="w-full text-left text-sm px-4 py-3 rounded-xl border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5 hover:bg-gray-100 dark:hover:bg-white/[0.08] hover:border-gray-300 dark:hover:border-white/20 text-gray-600 dark:text-white/60 hover:text-gray-900 dark:hover:text-white transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.map((msg, mi) =>
          msg.role === "user" ? (
            <div key={mi} className="flex justify-end">
              <div
                className="max-w-[78%] rounded-2xl rounded-br-md px-4 py-3 text-white text-sm leading-relaxed shadow-sm"
                style={{ backgroundColor: branding.primary_color }}
              >
                {msg.text}
              </div>
            </div>
          ) : (
            <div key={mi} className="flex justify-start gap-3">
              {/* Assistant avatar */}
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold shrink-0 mt-0.5 shadow-sm"
                style={{ backgroundColor: branding.primary_color }}
              >
                {branding.assistant_name.charAt(0)}
              </div>

              <div className="flex-1 min-w-0">
                {msg.steps && msg.steps.length > 0 && (
                  <StepTrail steps={msg.steps} live={msg.parts.length === 0 && !msg.error} />
                )}
                <div className="bg-gray-50 dark:bg-white/5 rounded-2xl rounded-tl-md px-4 py-3 border border-gray-200 dark:border-white/10 text-sm text-gray-700 dark:text-white/80 leading-relaxed">
                  {msg.parts.length === 0 && !msg.error ? (
                    <TypingDots color={branding.primary_color} />
                  ) : (
                    <div>
                      {groupParts(msg.parts).map((group, gi) => (
                        <div key={gi}>
                          {group.text && (
                            <ReactMarkdown remarkPlugins={[remarkGfm]}
                              components={{
                                p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                                ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-0.5">{children}</ul>,
                                ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-0.5">{children}</ol>,
                                li: ({ children }) => <li className="text-gray-700 dark:text-white/80">{children}</li>,
                                strong: ({ children }) => <strong className="font-semibold text-gray-900 dark:text-white">{children}</strong>,
                                code: ({ children }) => <code className="bg-gray-100 dark:bg-white/10 rounded px-1 py-0.5 text-xs font-mono">{children}</code>,
                                pre: ({ children }) => <pre className="bg-gray-100 dark:bg-white/10 rounded-lg p-3 mb-2 overflow-x-auto text-xs font-mono">{children}</pre>,
                                table: ({ children }) => (
                                  <div className="overflow-x-auto mb-2">
                                    <table className="w-full text-xs border-collapse">{children}</table>
                                  </div>
                                ),
                                thead: ({ children }) => <thead className="border-b border-gray-200 dark:border-white/20">{children}</thead>,
                                th: ({ children }) => <th className="text-left px-3 py-2 font-semibold text-gray-600 dark:text-white/70 whitespace-nowrap">{children}</th>,
                                td: ({ children }) => <td className="px-3 py-2 border-b border-gray-100 dark:border-white/10 text-gray-600 dark:text-white/70">{children}</td>,
                                h1: ({ children }) => <h1 className="text-base font-bold text-gray-900 dark:text-white mb-2">{children}</h1>,
                                h2: ({ children }) => <h2 className="text-sm font-bold text-gray-900 dark:text-white mb-1.5">{children}</h2>,
                                h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-1">{children}</h3>,
                                a: ({ href, children }) => <a href={href} className="underline text-gray-500 dark:text-white/70 hover:text-gray-900 dark:hover:text-white" target="_blank" rel="noreferrer">{children}</a>,
                              }}
                            >
                              {group.text}
                            </ReactMarkdown>
                          )}
                          {group.cites.length > 0 && (
                            <span className="inline-flex flex-wrap gap-0.5 mb-2">
                              {group.cites.map((cite, ci) => (
                                <CitationPopover key={ci} part={cite} color={branding.primary_color} />
                              ))}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {msg.error && (
                    <div className="flex items-center gap-2 text-red-500 dark:text-red-400 text-xs mt-2 pt-2 border-t border-red-200 dark:border-red-500/20">
                      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                      {msg.error}
                    </div>
                  )}
                </div>

                {msg.meta && (
                  <div className="flex items-center gap-3 mt-1.5 px-1 text-[11px] text-gray-400 dark:text-white/30">
                    <span>{(msg.meta.latency_ms / 1000).toFixed(1)}s</span>
                    <span>${msg.meta.cost_usd.toFixed(4)}</span>
                    {msg.meta.cache_read_input_tokens > 0 && (
                      <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400" />
                        {msg.meta.cache_read_input_tokens.toLocaleString()} cached
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        )}

        {/* Tool status (loop clients only — the pipeline reports progress as steps) */}
        {toolStatus && liveSteps.length === 0 && (
          <div className="flex justify-start gap-3">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold shrink-0 shadow-sm"
              style={{ backgroundColor: branding.primary_color }}
            >
              {branding.assistant_name.charAt(0)}
            </div>
            <div className="bg-gray-50 dark:bg-white/5 rounded-2xl rounded-tl-md px-4 py-3 border border-gray-200 dark:border-white/10">
              <div className="flex items-center gap-2 text-sm text-gray-400 dark:text-white/40">
                <svg
                  className="w-3.5 h-3.5 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {toolStatus}…
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="py-4 shrink-0">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
          className="flex items-end gap-3 bg-gray-50 dark:bg-white/5 rounded-2xl border border-gray-200 dark:border-white/10 px-4 py-3 focus-within:border-gray-300 dark:focus-within:border-white/20 transition-all"
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={`Message ${branding.assistant_name}…`}
            rows={1}
            className="flex-1 bg-transparent outline-none text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-white/30 text-sm resize-none leading-relaxed"
            style={{ maxHeight: "160px" }}
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || input.trim() === ""}
            className="shrink-0 w-8 h-8 rounded-xl flex items-center justify-center text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed hover:opacity-90"
            style={{ backgroundColor: branding.primary_color }}
            aria-label="Send"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </form>
        <p className="text-center text-[11px] text-gray-400 dark:text-white/30 mt-2">
          Answers grounded in {branding.name} documents · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
