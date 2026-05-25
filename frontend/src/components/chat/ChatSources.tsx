import { useState } from "react";
import { Source } from "@/lib/chat-store";
import { ChevronDown, ExternalLink, FileText, FileX } from "lucide-react";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";

interface ChatSourcesProps {
  sources?: Source[];
}

/**
 * Sources section. Always renders so the post-answer layout stays
 * consistent. When `sources` is undefined or empty we show a compact
 * "No sources available" state instead of hiding the whole block.
 */
export function ChatSources({ sources }: ChatSourcesProps) {
  const [expanded, setExpanded] = useState(false);
  const hasSources = !!sources && sources.length > 0;

  if (!hasSources) {
    return (
      <div className="mt-4 mb-2">
        <div className="inline-flex items-center gap-2 rounded-xl border border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground">
          <FileX className="h-3.5 w-3.5" />
          <span>No sources available</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground hover:border-primary/30"
      >
        <FileText className="h-3.5 w-3.5" />
        <span>
          {sources!.length} source{sources!.length !== 1 ? "s" : ""}
        </span>
        <ChevronDown
          className={cn("h-3 w-3 transition-transform duration-200", expanded && "rotate-180")}
        />
      </button>
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-2">
              {sources!.map((source, i) => (
                <a
                  key={i}
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-start gap-3 rounded-xl border border-border bg-background p-3 transition-all duration-200 hover:border-primary/30 hover:shadow-sm"
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <FileText className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-foreground transition-colors group-hover:text-primary">
                      {source.title}
                    </p>
                    <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
                      {source.snippet}
                    </p>
                  </div>
                  <ExternalLink className="mt-1 h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                </a>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
