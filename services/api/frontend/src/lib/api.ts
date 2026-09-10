// Frontend API client.
//
// All URLs are relative. In production FastAPI serves these built assets from
// the same origin, and in development Vite proxies these paths to the backend
// (see vite.config.ts), so neither case is a cross-origin request.
//
// The interesting part is askStream: /ask replies with newline-delimited JSON
// rather than a JSON document, so the response is consumed incrementally.
import { Source } from "@/lib/chat-store";

export interface QuotaInfo {
  available: boolean;
}
export interface QuotaResponse {
  status: boolean;
  quota: {
    thinking: QuotaInfo;
    primary: QuotaInfo;
  };
  timestamp: string;
}

export interface HealthResponse {
  status: boolean;
  message: string;
}

export interface HistoryEntry {
  role: "user" | "assistant";
  content: string;
}

// A thread the answer draws on, as sent by the backend. Deliberately not the
// same shape as the stored `Source`: mapping between them at the event boundary
// means conversations already in localStorage need no migration.
export interface StreamSource {
  permalink: string;
  title: string;
  snippet: string;
}

// One line of the /ask stream. Mirrors AskStreamEventModel in
// services/api/app/models/response/ask.py -- change both together.
export type StreamEvent =
  | { type: "step"; content: string }
  | { type: "token"; content: string }
  | { type: "sources"; sources: StreamSource[] }
  | { type: "done" }
  | { type: "error"; content: string };

export async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch("/health", { method: "GET" });
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function fetchQuota(): Promise<QuotaResponse> {
  const r = await fetch("/quota", { method: "GET" });
  if (!r.ok) throw new Error(`quota ${r.status}`);
  return r.json();
}

export async function rewriteQuery(query: string): Promise<string> {
  const r = await fetch("/rewriteQuery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!r.ok) throw new Error(`rewriteQuery ${r.status}`);
  const data = await r.json();
  return data?.query ?? query;
}

export interface AskOptions {
  query: string;
  thinking: boolean;
  history: HistoryEntry[];
  signal?: AbortSignal;
  onEvent: (evt: StreamEvent) => void;
}

export interface AskResult {
  status: number;
  ok: boolean;
}

export async function askStream({
  query,
  thinking,
  history,
  signal,
  onEvent,
}: AskOptions): Promise<AskResult> {

  // The backend wants one {query, answer} per exchange, but the UI stores a flat
  // list of messages. Pair each user message with the assistant reply that
  // follows it.
  //
  // Mapping per-message instead sent every exchange twice -- once as
  // {query, answer: ""} for the user message and again as {query, answer} for
  // the reply -- so the model saw the whole conversation duplicated, half of it
  // with blank answers.
  const formattedHistory: { query: string; answer: string }[] = [];
  for (let i = 0; i < history.length; i++) {
    if (history[i].role !== "user") continue;
    const reply = history[i + 1];
    formattedHistory.push({
      query: history[i].content,
      // A trailing user message with no reply yet (an aborted or failed turn)
      // still carries useful context, so keep it with an empty answer.
      answer: reply?.role === "assistant" ? reply.content : "",
    });
  }

  const resp = await fetch("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, thinking, history: formattedHistory }),
    signal,
  });

  if (!resp.ok || !resp.body) {
    return { status: resp.status, ok: false };
  }

  // Read the body as it arrives. A chunk is an arbitrary slice of bytes, so it
  // can split a JSON object -- or even a multi-byte character -- in half.
  // `stream: true` lets the decoder hold a partial character back, and `buffer`
  // does the same for a partial line.
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Process buffer in chunks, leaving partial lines for the next read
    let lastNewline = buffer.lastIndexOf("\n");
    // Wait for a full line
    if (lastNewline === -1) continue;

    const processable = buffer.substring(0, lastNewline);
    buffer = buffer.substring(lastNewline + 1);

    const events: StreamEvent[] = [];
    for (const line of processable.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        events.push(JSON.parse(trimmed) as StreamEvent);
      } catch {
        /*noop*/
      }
    }

    if (events.length > 0) {
      // Coalesce runs of tokens into one event. Each event triggers a React
      // state update, and the model emits tokens far faster than the browser can
      // usefully repaint; merging them cuts renders without changing the text.
      // Non-token events act as boundaries so ordering is preserved.
      const batchedEvents: StreamEvent[] = [];
      let tokenBuffer = "";

      for (const event of events) {
        if (event.type === "token") {
          tokenBuffer += event.content;
        } else {
          if (tokenBuffer) {
            batchedEvents.push({ type: "token", content: tokenBuffer });
            tokenBuffer = "";
          }
          batchedEvents.push(event);
        }
      }

      if (tokenBuffer) {
        batchedEvents.push({ type: "token", content: tokenBuffer });
      }

      batchedEvents.forEach(onEvent);
    }
  }

  // The stream ended without a trailing newline after the last object -- emit it
  // rather than dropping it, since that last line is usually `done`.
  const tail = buffer.trim();
  if (tail) {
    try {
      onEvent(JSON.parse(tail) as StreamEvent);
    } catch {
      /* noop */
    }
  }

  return { status: resp.status, ok: true };
}

/**
 * Pull a trailing citation list out of an answer and return the prose without it.
 *
 * This is a FALLBACK. Citations arrive as a `sources` stream event carrying the
 * threads retrieval actually selected, which is exact, and the system prompt
 * asks the model not to reprint them. Two cases still need this: conversations
 * restored from localStorage that predate the event, and a model that writes a
 * Sources list regardless of being told not to.
 */
export function extractSources(content: string): { cleanContent: string; sources: Source[] } {
  const sources: Source[] = [];

  // First, extract from **Sources:** section if it exists
  const sourcesSectionMatch = content.match(
    /\n*\*?\*?Sources?\*?\*?:?\s*\n+([\s\S]*?)$/i
  );

  if (sourcesSectionMatch) {
    const sourcesText = sourcesSectionMatch[1];
    const markdownMatches = sourcesText.matchAll(/\[-•*]?\s*\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g);
    for (const match of markdownMatches) {
      const [, linkText, url] = match;
      sources.push({
        title: linkText.trim(),
        url,
        snippet: linkText.trim(),
      });
    }
  }

  // Strip a trailing Sources section, and nothing else. Deleting every
  // bullet-pointed markdown link anywhere in the answer would be safe only if
  // such lines were guaranteed to be citations; the system prompt asks for no
  // source list, so a link inside a genuine list is part of the answer and has
  // to survive.
  const cleanContent = content
    .replace(/\n*\*?\*?Sources?\*?\*?:?\s*\n+([\s\S]*)$/i, "")
    .trim();

  return { cleanContent, sources };
}
