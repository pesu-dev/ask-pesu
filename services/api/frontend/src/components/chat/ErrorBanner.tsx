import { AlertTriangle, RefreshCw, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

interface ErrorBannerProps {
  message: string | null;
  onRetry?: () => void;
  onDismiss?: () => void;
  retrying?: boolean;
}

/**
 * Inline, non-blocking error banner shown above the chat input when the
 * latest /ask or /health request fails. Clears automatically on the next
 * successful request (parent clears `message`).
 */
export function ErrorBanner({ message, onRetry, onDismiss, retrying }: ErrorBannerProps) {
  return (
    <AnimatePresence>
      {message && (
        <motion.div
          initial={{ opacity: 0, y: -6, height: 0 }}
          animate={{ opacity: 1, y: 0, height: "auto" }}
          exit={{ opacity: 0, y: -6, height: 0 }}
          transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          className="overflow-hidden"
        >
          <div className="flex items-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="flex-1 leading-snug">{message}</span>
            {onRetry && (
              <button
                onClick={onRetry}
                disabled={retrying}
                className={cn(
                  "flex items-center gap-1 rounded-md border border-destructive/40 bg-background/60 px-2 py-1 text-[11px] font-medium transition-colors hover:bg-background disabled:opacity-60"
                )}
              >
                <RefreshCw className={cn("h-3 w-3", retrying && "animate-spin")} />
                Retry
              </button>
            )}
            {onDismiss && (
              <button
                onClick={onDismiss}
                className="rounded-md p-1 opacity-70 hover:bg-background/60 hover:opacity-100"
                aria-label="Dismiss"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
