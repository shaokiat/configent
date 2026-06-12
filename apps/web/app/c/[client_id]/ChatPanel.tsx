"use client";

import { useEffect, useRef, useState } from "react";

interface BrandingData {
  id: string;
  name: string;
  primary_color: string;
  logo: string;
  assistant_name: string;
}

type Part =
  | { kind: "text"; text: string }
  | { kind: "cite"; index: number; source: string; title: string; cited_text: string };

interface TurnMeta {
  cost_usd: number;
  latency_ms: number;
  cache_read_input_tokens: number;
}

type ChatMessage =
  | { role: "user"; text: string }
  | { role: "assistant"; parts: Part[]; meta?: TurnMeta; error?: string };

interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

/** Pull complete `event:`/`data:` frames out of the buffer; return the remainder. */
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
        // Drop malformed frames rather than killing the stream
      }
    }
  }
  return { events, rest: buffer };
}

function toolLabel(name: string): string {
  if (name === "search_docs") return "Searching documents…";
  if (name === "get_document") return "Opening document…";
  return `Running ${name}…`;
}

export default function ChatPanel({ branding }: { branding: BrandingData }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [openCite, setOpenCite] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolStatus]);

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
    } else if (event === "done") {
      setConversationId(data.conversation_id as string);
      updateLastAssistant((msg) => {
        msg.meta = {
          cost_usd: data.cost_usd as number,
          latency_ms: data.latency_ms as number,
          cache_read_input_tokens: data.cache_read_input_tokens as number,
        };
      });
    } else if (event === "error") {
      updateLastAssistant((msg) => {
        msg.error = (data.message as string) || "Something went wrong.";
      });
    }
  }

  async function send() {
    const question = input.trim();
    if (!question || streaming) return;
    setInput("");
    setOpenCite(null);
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
    (messages[messages.length - 1] as Extract<ChatMessage, { role: "assistant" }>).parts
      .length === 0;

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full max-w-3xl mx-auto">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center mt-8">
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center text-white text-2xl font-bold mx-auto mb-4"
              style={{ backgroundColor: branding.primary_color }}
            >
              {branding.assistant_name.charAt(0)}
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              {branding.assistant_name}
            </h2>
            <p className="text-gray-500">
              Your AI assistant for {branding.name}. Ask me anything about our
              documentation — answers come with citations.
            </p>
          </div>
        )}

        {messages.map((msg, mi) =>
          msg.role === "user" ? (
            <div key={mi} className="flex justify-end">
              <div
                className="max-w-[80%] rounded-2xl rounded-br-sm px-4 py-2.5 text-white text-sm whitespace-pre-wrap"
                style={{ backgroundColor: branding.primary_color }}
              >
                {msg.text}
              </div>
            </div>
          ) : (
            <div key={mi} className="flex justify-start">
              <div className="max-w-[85%] bg-white rounded-2xl rounded-bl-sm px-4 py-2.5 border border-gray-200 shadow-sm text-sm text-gray-800">
                <div className="whitespace-pre-wrap leading-relaxed">
                  {msg.parts.map((part, pi) => {
                    if (part.kind === "text") {
                      return <span key={pi}>{part.text}</span>;
                    }
                    const citeKey = `${mi}-${pi}`;
                    return (
                      <span key={pi} className="relative inline-block">
                        <button
                          onClick={() => setOpenCite(openCite === citeKey ? null : citeKey)}
                          className="align-super text-[10px] font-semibold px-1 rounded hover:bg-gray-100 cursor-pointer"
                          style={{ color: branding.primary_color }}
                          aria-label={`Citation ${part.index}: ${part.title}`}
                        >
                          [{part.index}]
                        </button>
                        {openCite === citeKey && (
                          <span className="absolute z-10 left-0 top-5 w-72 bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs text-left normal-case">
                            <span className="block font-semibold text-gray-900 mb-1">
                              {part.title}
                            </span>
                            <span className="block text-gray-600 italic mb-1">
                              “{part.cited_text}”
                            </span>
                            <span className="block text-gray-400 truncate">{part.source}</span>
                          </span>
                        )}
                      </span>
                    );
                  })}
                </div>
                {msg.error && (
                  <div className="text-red-600 text-xs mt-2">⚠ {msg.error}</div>
                )}
                {msg.meta && (
                  <div className="text-[10px] text-gray-400 mt-2 pt-1.5 border-t border-gray-100">
                    ${msg.meta.cost_usd.toFixed(4)} ·{" "}
                    {(msg.meta.latency_ms / 1000).toFixed(1)}s ·{" "}
                    {msg.meta.cache_read_input_tokens.toLocaleString()} cached tokens
                  </div>
                )}
              </div>
            </div>
          )
        )}

        {(toolStatus || lastIsEmptyAssistant) && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 text-xs text-gray-500 px-4 py-2">
              <span
                className="w-2 h-2 rounded-full animate-pulse"
                style={{ backgroundColor: branding.primary_color }}
              />
              {toolStatus ?? "Thinking…"}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="px-4 pb-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
          className="flex items-center gap-3 bg-white rounded-xl p-3 border border-gray-200 shadow-sm"
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`Ask ${branding.assistant_name} a question…`}
            className="flex-1 bg-transparent outline-none text-gray-700 placeholder-gray-400 text-sm"
            disabled={streaming}
          />
          <button
            type="submit"
            disabled={streaming || input.trim() === ""}
            className="px-4 py-1.5 rounded-md text-white text-sm font-medium transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ backgroundColor: branding.primary_color }}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
