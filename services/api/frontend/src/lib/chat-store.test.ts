import { webcrypto } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { loadConversations, saveConversations } from "./chat-persistence";
import { createConversation, createId } from "./chat-store";

beforeAll(() => vi.stubGlobal("crypto", webcrypto));
afterAll(() => vi.unstubAllGlobals());

describe("conversation IDs", () => {
  it("generates UUIDs without collisions in 1,000 calls", () => {
    const ids = Array.from({ length: 1_000 }, () => createId());

    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    }
  });

  it("loads conversations with old IDs alongside new UUIDs", () => {
    const legacy = {
      ...createConversation("Earlier chat"),
      id: "old-style-id",
      messages: [
        {
          id: "old-message-id",
          role: "user" as const,
          content: "Hello",
          timestamp: new Date("2026-01-01T00:00:00Z"),
        },
      ],
    };
    const current = createConversation("New chat");

    saveConversations([legacy, current]);
    const loaded = loadConversations();

    expect(loaded.map((conversation) => conversation.id)).toEqual([legacy.id, current.id]);
    expect(loaded[0].messages[0].id).toBe("old-message-id");
    expect(loaded[0].messages[0].timestamp).toEqual(legacy.messages[0].timestamp);
  });
});
