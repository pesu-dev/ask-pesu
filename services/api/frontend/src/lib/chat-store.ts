// Types and helpers for the conversation model held in React state.
// A conversation is a list of messages plus the sources attached to assistant
// replies; nothing here talks to the network or to storage.
export interface Source {
  title: string;
  url: string;
  snippet: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  timestamp: Date;
  /** True when content arrived via live /ask streaming (skip the fake word animation in ChatMessage). */
  streamed?: boolean;
  /** Optional ephemeral status text (e.g. "Searching documents...") shown while tokens are still arriving. */
  status?: string;
  /** Set when the stream aborted mid-flight (backend error, network drop, /ask returned non-2xx). */
  error?: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
}

export function createId(): string {
  return Math.random().toString(36).substring(2, 15);
}

export function createConversation(title: string = "New Chat"): Conversation {
  return {
    id: createId(),
    title,
    messages: [],
    createdAt: new Date(),
    updatedAt: new Date(),
  };
}
