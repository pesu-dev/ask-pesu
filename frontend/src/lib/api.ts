// Frontend API client. All URLs are relative so the FastAPI backend can
// serve the built assets on the same origin without any CORS config.
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

export type StreamEvent =
  | { type: "step"; content: string }
  | { type: "token"; content: string }
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
  const resp = await fetch("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, thinking, history }),
    signal,
  });

  if (!resp.ok || !resp.body) {
    return { status: resp.status, ok: false };
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Process buffer in chunks, leaving partial lines for the next read
    let lastNewline = buffer.lastIndexOf("\n");
    if (lastNewline === -1) continue; // Wait for a full line

    const processable = buffer.substring(0, lastNewline);
    buffer = buffer.substring(lastNewline + 1);

    const events: StreamEvent[] = [];
    for (const line of processable.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        events.push(JSON.parse(trimmed) as StreamEvent);
      } catch {
        // ignore malformed line
      }
    }

    if (events.length > 0) {
      // Batch 'token' events for smoother rendering
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

  // flush any trailing buffered line
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

  // If no sources found in dedicated section, extract from inline markdown links
  if (sources.length === 0) {
    const inlineMatches = content.matchAll(/[-•*]\s+\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g);
    for (const match of inlineMatches) {
      const [, linkText, url] = match;
      sources.push({
        title: linkText.trim(),
        url,
        snippet: linkText.trim(),
      });
    }
  }

  // Remove the Sources section and any inline source-like markdown links
  let cleanContent = content
    .replace(/\n*\*?\*?Sources?\*?\*?:?\s*\n+([\s\S]*)$/i, "") // Remove Sources section
    .trim();

  // Remove lines that are just markdown links (source citations)
  cleanContent = cleanContent
    .split('\n')
    .filter(line => {
      const trimmed = line.trim();
      // Skip lines that are just bullet-pointed markdown links
      return !trimmed.match(/^[-•*]\s+\[([^\]]+)\]\((https?:\/\/[^\)]+)\)$/);
    })
    .join('\n')
    .trim();

  return { cleanContent, sources };
}
