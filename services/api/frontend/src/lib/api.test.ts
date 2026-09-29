import { describe, expect, it } from "vitest";
import { extractSources } from "./api";

describe("extractSources", () => {
  it("extracts links from a trailing Sources section", () => {
    const answer =
      "Here is the answer.\n\n**Sources:**\n- [Thread one](https://reddit.com/a)\n- [Thread two](https://reddit.com/b)";

    expect(extractSources(answer)).toEqual({
      cleanContent: "Here is the answer.",
      sources: [
        { title: "Thread one", url: "https://reddit.com/a", snippet: "Thread one" },
        { title: "Thread two", url: "https://reddit.com/b", snippet: "Thread two" },
      ],
    });
  });

  it.each(["*", "•", ""])("accepts %s bullets", (bullet) => {
    const line = bullet ? `${bullet} [Discussion](https://reddit.com/c)` : "[Discussion](https://reddit.com/c)";
    expect(extractSources(`Answer\nSources:\n${line}`)).toEqual({
      cleanContent: "Answer",
      sources: [{ title: "Discussion", url: "https://reddit.com/c", snippet: "Discussion" }],
    });
  });

  it("leaves answers without a Sources section unchanged", () => {
    const answer = "Read [the guide](https://example.com/guide) for details.";
    expect(extractSources(answer)).toEqual({ cleanContent: answer, sources: [] });
  });

  it("keeps links in the answer body", () => {
    const answer =
      "See [the guide](https://example.com/guide).\n\nSources:\n- [Discussion](https://reddit.com/c)";
    expect(extractSources(answer)).toEqual({
      cleanContent: "See [the guide](https://example.com/guide).",
      sources: [{ title: "Discussion", url: "https://reddit.com/c", snippet: "Discussion" }],
    });
  });
});
