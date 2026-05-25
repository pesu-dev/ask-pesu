import { useEffect, useState, useRef, useCallback } from "react";
import { Conversation } from "@/lib/chat-store";
import { Search, MessageSquare, CornerDownLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion } from "framer-motion";

interface SearchResult {
  conversationId: string;
  conversationTitle: string;
  matchType: "title" | "message";
  messageSnippet?: string;
  messageRole?: "user" | "assistant";
}

interface CommandSearchProps {
  conversations: Conversation[];
  onSelect: (id: string) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function CommandSearch({ conversations, onSelect, open: controlledOpen, onOpenChange }: CommandSearchProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const open = controlledOpen ?? internalOpen;
  const setOpen = (v: boolean) => {
    setInternalOpen(v);
    onOpenChange?.(v);
  };

  // Search both titles and message content
  const results: SearchResult[] = (() => {
    if (!query.trim()) {
      // Show recent conversations when no query
      return conversations.slice(0, 8).map((c) => ({
        conversationId: c.id,
        conversationTitle: c.title,
        matchType: "title" as const,
      }));
    }

    const q = query.toLowerCase();
    const found: SearchResult[] = [];

    conversations.forEach((conv) => {
      // Title match
      if (conv.title.toLowerCase().includes(q)) {
        found.push({
          conversationId: conv.id,
          conversationTitle: conv.title,
          matchType: "title",
        });
      }

      // Message content match
      conv.messages.forEach((msg) => {
        if (msg.content.toLowerCase().includes(q)) {
          // Extract snippet around match
          const idx = msg.content.toLowerCase().indexOf(q);
          const start = Math.max(0, idx - 30);
          const end = Math.min(msg.content.length, idx + query.length + 40);
          const snippet =
            (start > 0 ? "..." : "") +
            msg.content.slice(start, end).replace(/\n/g, " ") +
            (end < msg.content.length ? "..." : "");

          // Avoid duplicate conversation entries
          if (!found.some((r) => r.conversationId === conv.id && r.matchType === "message")) {
            found.push({
              conversationId: conv.id,
              conversationTitle: conv.title,
              matchType: "message",
              messageSnippet: snippet,
              messageRole: msg.role,
            });
          }
        }
      });
    });

    return found.slice(0, 12);
  })();

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!open) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && results.length > 0) {
        e.preventDefault();
        const selected = results[selectedIndex];
        if (selected) {
          onSelect(selected.conversationId);
          setOpen(false);
        }
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    },
    [open, results, selectedIndex, onSelect]
  );

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(!open);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [open]);

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Reset selection when query changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return;
    const items = listRef.current.querySelectorAll("[data-search-item]");
    items[selectedIndex]?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-50 flex items-start justify-center pt-[18vh]"
        onClick={() => setOpen(false)}
      >
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute inset-0 bg-background/60 backdrop-blur-md"
        />

        {/* Dialog */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: -12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: -12 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          onClick={(e) => e.stopPropagation()}
          className="relative w-full max-w-[520px] mx-4 overflow-hidden rounded-2xl border border-border bg-popover shadow-2xl"
        >
          {/* Search input */}
          <div className="flex items-center gap-3 border-b border-border px-4 py-3.5">
            <Search className="h-4.5 w-4.5 shrink-0 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search conversations and messages..."
              className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
            <kbd className="hidden sm:inline-flex items-center gap-0.5 rounded-md border border-border bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div ref={listRef} className="max-h-[320px] overflow-y-auto p-1.5">
            {results.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                No results found.
              </div>
            ) : (
              <div>
                <p className="px-2.5 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {query.trim() ? "Results" : "Recent Chats"}
                </p>
                {results.map((result, i) => (
                  <button
                    key={`${result.conversationId}-${result.matchType}-${i}`}
                    data-search-item
                    onClick={() => {
                      onSelect(result.conversationId);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-start gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                      i === selectedIndex
                        ? "bg-accent text-accent-foreground"
                        : "text-foreground hover:bg-muted/60"
                    )}
                  >
                    <MessageSquare className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{result.conversationTitle}</span>
                      {result.matchType === "message" && result.messageSnippet && (
                        <span className="block mt-0.5 truncate text-xs text-muted-foreground">
                          {result.messageSnippet}
                        </span>
                      )}
                    </div>
                    {i === selectedIndex && (
                      <CornerDownLeft className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Footer hints */}
          <div className="flex items-center gap-4 border-t border-border px-4 py-2">
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[9px]">&uarr;&darr;</kbd>
              Navigate
            </span>
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[9px]">&crarr;</kbd>
              Open
            </span>
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[9px]">esc</kbd>
              Close
            </span>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
