import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { Message } from "@/lib/chat-store";
import { MessageActions } from "./MessageActions";
import { ChatSources } from "./ChatSources";
import { motion } from "framer-motion";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface ChatMessageProps {
  message: Message;
  isLatest?: boolean;
  onRetry?: () => void;
  onThinkLonger?: () => void;
  isLoading?: boolean;
}

const streamedAssistantMessageIds = new Set<string>();

function splitIntoWordChunks(content: string) {
  return content.match(/\S+\s*/g) ?? [];
}

export function ChatMessage({
  message,
  isLatest = false,
  onRetry,
  onThinkLonger,
  isLoading = false,
}: ChatMessageProps) {
  const isUser = message.role === "user";
  const shouldStream =
    !isUser &&
    isLatest &&
    !message.streamed &&
    !streamedAssistantMessageIds.has(message.id);
  const [visibleContent, setVisibleContent] = useState(
    shouldStream ? "" : message.content,
  );
  const [streamingComplete, setStreamingComplete] = useState(!shouldStream);
  const assistantMessageRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!shouldStream) {
      setVisibleContent(message.content);
      setStreamingComplete(true);
      return;
    }

    const chunks = splitIntoWordChunks(message.content);

    if (chunks.length === 0) {
      streamedAssistantMessageIds.add(message.id);
      setVisibleContent(message.content);
      setStreamingComplete(true);
      return;
    }

    let index = 0;
    const step = chunks.length > 120 ? 3 : chunks.length > 60 ? 2 : 1;

    setVisibleContent("");
    setStreamingComplete(false);

    const timer = window.setInterval(() => {
      index = Math.min(index + step, chunks.length);
      setVisibleContent(chunks.slice(0, index).join(""));

      if (index >= chunks.length) {
        window.clearInterval(timer);
        streamedAssistantMessageIds.add(message.id);
        setStreamingComplete(true);
      }
    }, 36);

    return () => window.clearInterval(timer);
  }, [message.content, message.id, shouldStream]);

  useEffect(() => {
    if (isUser || !isLatest) return;
    const node = assistantMessageRef.current;
    if (!node) return;
    // Find the nearest scroll container and only auto-scroll when the user
    // is already near the bottom. This lets the user scroll up to re-read
    // earlier content mid-stream without being yanked back down.
    let container: HTMLElement | null = node.parentElement;
    while (container && container !== document.body) {
      const style = getComputedStyle(container);
      if (/(auto|scroll)/.test(style.overflowY)) break;
      container = container.parentElement;
    }
    if (!container) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceFromBottom < 160) {
      node.scrollIntoView({
        behavior: streamingComplete ? "smooth" : "auto",
        block: "end",
      });
    }
  }, [visibleContent, isLatest, isUser, streamingComplete]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
      className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}
    >
      {isUser ? (
        <div className="max-w-[85%] md:max-w-[70%] rounded-2xl bg-primary px-4 py-2.5 text-primary-foreground shadow-md shadow-primary/15">
          <p className="whitespace-pre-wrap text-base leading-relaxed">
            {message.content}
          </p>
        </div>
      ) : (
        <div ref={assistantMessageRef} className="w-full max-w-none">
          {message.status && !message.content && (
            <p className="text-sm text-muted-foreground italic mb-2 animate-pulse">
              {message.status}
            </p>
          )}
          <div className="prose">
            <ReactMarkdown
              remarkPlugins={[remarkMath, remarkGfm]}
              rehypePlugins={[rehypeKatex]}
            >
              {visibleContent}
            </ReactMarkdown>
            {((shouldStream && !streamingComplete) ||
              (message.streamed && isLatest && message.status)) && (
              <span
                aria-hidden="true"
                className="ml-0.5 inline-block h-4 w-px align-middle bg-primary/60 animate-pulse"
              />
            )}
          </div>

          {message.error && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span className="flex-1 leading-snug">{message.error}</span>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="flex items-center gap-1 rounded-md border border-destructive/40 bg-background/60 px-2 py-1 text-[11px] font-medium transition-colors hover:bg-background"
                >
                  <RefreshCw className="h-3 w-3" />
                  Retry
                </button>
              )}
            </div>
          )}

          {streamingComplete &&
            message.content &&
            !message.error &&
            !isLoading && (
              <>
                <ChatSources sources={message.sources} />
              </>
            )}
          {streamingComplete &&
            !message.status &&
            message.content &&
            !message.error &&
            !isLoading && (
              <MessageActions
                content={message.content}
                onThinkLonger={onThinkLonger}
              />
            )}
        </div>
      )}
    </motion.div>
  );
}
