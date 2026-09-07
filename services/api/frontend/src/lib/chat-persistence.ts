// Conversation persistence, in the browser only.
//
// There is no server-side chat storage: conversations live in localStorage under
// a single key, and the client replays the relevant history with each /ask call.
// That means history is per-device and clearing site data loses it -- a
// deliberate trade for storing nothing about users on the server.
import { Conversation } from "./chat-store";

const STORAGE_KEY = "askpesu-conversations";

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return parsed.map((c: any) => ({
      ...c,
      createdAt: new Date(c.createdAt),
      updatedAt: new Date(c.updatedAt),
      messages: c.messages.map((m: any) => ({
        ...m,
        timestamp: new Date(m.timestamp),
      })),
    }));
  } catch {
    return [];
  }
}

export function saveConversations(conversations: Conversation[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  } catch {
    // storage full or unavailable
  }
}
