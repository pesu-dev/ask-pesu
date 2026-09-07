// The chat screen: conversation list, message thread, composer.
//
// Owns the streaming lifecycle. Two paths call askStream -- handleSubmit for a
// normal question and handleThinkLonger for re-answering an existing reply with
// the thinking model -- and both must handle all four event types, since a
// dropped `error` event leaves a failure invisible.
//
// Tokens are buffered and flushed on requestAnimationFrame: the model emits far
// faster than the browser can usefully repaint, so applying every token as its
// own state update would thrash React for no visible gain.
import { useState, useRef, useCallback, useEffect } from "react";
import { AnimatePresence, motion, PanInfo } from "framer-motion";
import { AppSidebar } from "@/components/AppSidebar";
import {
  ChatInput,
  ChatInputTextArea,
  ChatInputSubmit,
} from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { CommandSearch } from "@/components/chat/CommandSearch";
import { LoadingBreadcrumb } from "@/components/chat/Loader";
import { ErrorBanner } from "@/components/chat/ErrorBanner";
import { Menu } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";
import { useTheme } from "@/hooks/use-theme";
import { useSidebarState } from "@/hooks/use-sidebar-state";
import { useHealth } from "@/hooks/use-health";
import {
  Conversation,
  Message,
  createConversation,
  createId,
} from "@/lib/chat-store";
import {
  askStream,
  rewriteQuery,
  HistoryEntry,
  extractSources,
} from "@/lib/api";
import { loadConversations, saveConversations } from "@/lib/chat-persistence";

const SIDEBAR_W = 280;

export default function Index() {
  const [conversations, setConversations] = useState<Conversation[]>(() =>
    loadConversations(),
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastQueryRef = useRef<string | null>(null);
  const isMobile = useIsMobile();

  const { theme, setTheme } = useTheme();
  const { collapsed, setCollapsed } = useSidebarState();
  const { available: serviceAvailable, error: healthError } = useHealth();

  // Thinking state
  const [thinkingEnabled, setThinkingEnabled] = useState(false);

  // Persist conversations to localStorage on change
  useEffect(() => {
    saveConversations(conversations);
  }, [conversations]);

  // Surface health failures in the banner; cleared on recovery.
  useEffect(() => {
    if (healthError) {
      setErrorMsg(
        "Backend service is unreachable. Check your connection or try again.",
      );
    } else if (serviceAvailable) {
      setErrorMsg((prev) =>
        prev && prev.startsWith("Backend service is unreachable") ? null : prev,
      );
    }
  }, [healthError, serviceAvailable]);

  const activeConversation =
    conversations.find((c) => c.id === activeId) ?? null;
  const hasMessages =
    activeConversation && activeConversation.messages.length > 0;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "/" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setSearchOpen(true);
      }
      if (e.key === "n" && (e.metaKey || e.ctrlKey) && e.shiftKey) {
        e.preventDefault();
        handleNewChat();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }, 50);
  }, []);

  const handleNewChat = () => {
    abortRef.current?.abort();
    setActiveId(null);
    setInput("");
  };

  const updateAssistantMessage = (
    convId: string,
    msgId: string,
    updater: (m: Message) => Message,
  ) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              messages: c.messages.map((m) =>
                m.id === msgId ? updater(m) : m,
              ),
              updatedAt: new Date(),
            }
          : c,
      ),
    );
  };

  const runQuery = async (
    trimmed: string,
    convId: string,
    assistantId: string,
    history: HistoryEntry[],
  ) => {
    // Buffer tokens in a ref and flush on animation frames so the UI
    // appends smoothly even when tokens arrive in tight bursts.
    let pendingTokens = "";
    let flushScheduled = false;
    let streamClosed = false; // set on done OR error; no further tokens are written

    const flush = () => {
      flushScheduled = false;
      if (!pendingTokens) return;
      const chunk = pendingTokens;
      pendingTokens = "";
      updateAssistantMessage(convId, assistantId, (m) => ({
        ...m,
        content: m.content + chunk,
        status: undefined,
      }));
    };

    const scheduleFlush = () => {
      if (flushScheduled || streamClosed) return;
      flushScheduled = true;
      requestAnimationFrame(flush);
    };

    const failStream = (reason: string) => {
      // Stop token appending immediately, drop anything still buffered,
      // and surface an inline error under the message with a retry button.
      streamClosed = true;
      pendingTokens = "";
      abortRef.current?.abort();
      updateAssistantMessage(convId, assistantId, (m) => ({
        ...m,
        status: undefined,
        error: reason,
      }));
      setErrorMsg(reason);
    };

    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const result = await askStream({
        query: trimmed,
        thinking: thinkingEnabled,
        history,
        signal: ac.signal,
        onEvent: (evt) => {
          if (streamClosed) return; // ignore anything arriving after fail/done
          if (evt.type === "step") {
            updateAssistantMessage(convId, assistantId, (m) => ({
              ...m,
              status: evt.content,
            }));
          } else if (evt.type === "token") {
            pendingTokens += evt.content;
            scheduleFlush();
          } else if (evt.type === "done") {
            streamClosed = true;
            flush();
            updateAssistantMessage(convId, assistantId, (m) => {
              const { cleanContent, sources } = extractSources(m.content);
              return {
                ...m,
                content: cleanContent,
                sources,
                status: undefined,
              };
            });
          } else if (evt.type === "error") {
            failStream(evt.content || "The model returned an error.");
          }
        },
      });

      // Final flush in case the stream ended without an explicit "done" event.
      if (!streamClosed) {
        streamClosed = true;
        flush();
      }

      if (!result.ok) {
        const msg =
          result.status === 429
            ? "Quota exceeded. Please try again later."
            : `Request failed (${result.status}). Please retry.`;
        updateAssistantMessage(convId, assistantId, (m) => ({
          ...m,
          status: undefined,
          error: msg,
        }));
        setErrorMsg(msg);
        return { ok: false as const };
      }

      setErrorMsg(null);
      return { ok: true as const };
    } catch (err: any) {
      streamClosed = true;
      pendingTokens = "";
      if (err?.name !== "AbortError") {
        const msg = "Network error while contacting the backend. Please retry.";
        updateAssistantMessage(convId, assistantId, (m) => ({
          ...m,
          status: undefined,
          error: msg,
        }));
        setErrorMsg(msg);
        return { ok: false as const };
      }
      // Abort was intentional (user clicked Stop or failStream fired);
      // just clear the transient status and keep whatever was streamed.
      updateAssistantMessage(convId, assistantId, (m) => ({
        ...m,
        status: undefined,
      }));
      return { ok: true as const };
    } finally {
      abortRef.current = null;
    }
  };

  const handleThinkLonger = async (
    convId: string,
    assistantId: string,
    userMessage: string,
  ) => {
    setLoading(true);
    setThinkingEnabled(true);

    // Get current conversation
    const conversation = conversations.find((c) => c.id === convId);
    if (!conversation) {
      setLoading(false);
      return;
    }

    // Build history excluding the current assistant message being deepened
    // Include ONLY messages before this assistant message, mapped to clean HistoryEntry
    const assistantMsgIndex = conversation.messages.findIndex(
      (m) => m.id === assistantId,
    );
    const userMsgIndex = assistantMsgIndex - 1;
    const history: HistoryEntry[] = conversation.messages
      .slice(0, userMsgIndex)
      .map((m) => ({ role: m.role, content: m.content }));

    // Create a new assistant message for the thinking response
    const thinkingResponseId = createId();
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              messages: [
                ...c.messages,
                {
                  id: thinkingResponseId,
                  role: "assistant" as const,
                  content: "",
                  timestamp: new Date(),
                  status: "Thinking with extended reasoning...",
                },
              ],
              updatedAt: new Date(),
            }
          : c,
      ),
    );

    // Create a NEW AbortController for the thinking request
    const ac = new AbortController();
    abortRef.current = ac;

    let pendingTokens = "";
    let flushScheduled = false;
    let streamClosed = false;

    const flush = () => {
      flushScheduled = false;
      if (!pendingTokens) return;
      const chunk = pendingTokens;
      pendingTokens = "";
      updateAssistantMessage(convId, thinkingResponseId, (m) => ({
        ...m,
        content: m.content + chunk,
      }));
    };

    const scheduleFlush = () => {
      if (flushScheduled || streamClosed) return;
      flushScheduled = true;
      requestAnimationFrame(flush);
    };

    try {
      await askStream({
        query: userMessage,
        thinking: true,
        history, // Now includes only previous messages, not the one being deepened
        signal: ac.signal, // NEW AbortController signal
        onEvent: (evt) => {
          if (streamClosed) return; // ignore anything arriving after fail/done
          if (evt.type === "step") {
            // Reasoning text from the thinking model. Dropping these was
            // especially wrong here: this handler exists to run that model, so
            // it was the one path guaranteed to produce steps.
            updateAssistantMessage(convId, thinkingResponseId, (m) => ({
              ...m,
              status: evt.content,
            }));
          } else if (evt.type === "token") {
            pendingTokens += evt.content;
            scheduleFlush();
          } else if (evt.type === "done") {
            streamClosed = true;
            flush();
            updateAssistantMessage(convId, thinkingResponseId, (m) => {
              const { cleanContent, sources } = extractSources(m.content);
              return {
                ...m,
                content: cleanContent,
                sources,
                status: undefined,
              };
            });
          } else if (evt.type === "error") {
            // The backend reports a mid-stream failure as an error event and
            // then done. Without this branch, done finalised an empty message
            // and the failure was invisible. Closing the stream here makes the
            // trailing done a no-op.
            streamClosed = true;
            flush();
            updateAssistantMessage(convId, thinkingResponseId, (m) => ({
              ...m,
              status: undefined,
              error: evt.content || "The model returned an error.",
            }));
          }
        },
      });
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        updateAssistantMessage(convId, thinkingResponseId, (m) => ({
          ...m,
          status: undefined,
          error: "Think longer request failed. Please try again.",
        }));
      }
    } finally {
      setThinkingEnabled(false);
      setLoading(false);
      abortRef.current = null;
    }
  };

  const handleSubmit = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    let conv = activeConversation;
    let isNewConv = false;
    if (!conv) {
      conv = createConversation(trimmed.slice(0, 50));
      isNewConv = true;
      setConversations((prev) => [conv!, ...prev]);
      setActiveId(conv.id);
    }

    const convId = conv.id;
    const userMsg: Message = {
      id: createId(),
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };
    const history: HistoryEntry[] = conv.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const assistantId = createId();
    const assistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      timestamp: new Date(),
      streamed: true,
      status: "Thinking...",
    };

    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              messages: [...c.messages, userMsg, assistantMsg],
              updatedAt: new Date(),
            }
          : c,
      ),
    );
    setInput("");
    setLoading(true);
    setErrorMsg(null);
    lastQueryRef.current = trimmed;
    scrollToBottom();

    if (isNewConv) {
      rewriteQuery(trimmed)
        .then((title) => {
          if (title && title.trim()) {
            setConversations((prev) =>
              prev.map((c) =>
                c.id === convId ? { ...c, title: title.trim() } : c,
              ),
            );
          }
        })
        .catch(() => {
          /* keep fallback title */
        });
    }

    await runQuery(trimmed, convId, assistantId, history);
    setLoading(false);
    scrollToBottom();
  };

  const handleRetry = async () => {
    if (!activeConversation || retrying || loading) {
      // Fallback: re-run last query from scratch if we don't have an active convo.
      if (lastQueryRef.current && !loading) {
        setInput(lastQueryRef.current);
      }
      return;
    }
    // Find the last assistant message and retry with its preceding history.
    const msgs = activeConversation.messages;
    const lastAssistantIdx = [...msgs]
      .reverse()
      .findIndex((m) => m.role === "assistant");
    if (lastAssistantIdx === -1) return;
    const realIdx = msgs.length - 1 - lastAssistantIdx;
    const lastUser = [...msgs.slice(0, realIdx)]
      .reverse()
      .find((m) => m.role === "user");
    if (!lastUser) return;

    setRetrying(true);
    const history: HistoryEntry[] = msgs
      .slice(0, realIdx)
      .filter((m) => m !== lastUser)
      .map((m) => ({ role: m.role, content: m.content }));
    const assistantId = msgs[realIdx].id;
    updateAssistantMessage(activeConversation.id, assistantId, (m) => ({
      ...m,
      content: "",
      status: "Thinking...",
      streamed: true,
      sources: undefined,
      error: undefined,
    }));
    setLoading(true);
    await runQuery(
      lastUser.content,
      activeConversation.id,
      assistantId,
      history,
    );
    setLoading(false);
    setRetrying(false);
    scrollToBottom();
  };

  const handleStop = () => {
    abortRef.current?.abort();
    setLoading(false);
  };

  const handleDelete = (id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(null);
  };

  const handleRename = (id: string, title: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c)),
    );
  };

  const handleSwipeDrag = (_: any, info: PanInfo) => {
    if (!sidebarOpen && info.offset.x > 60 && info.velocity.x > 100) {
      setSidebarOpen(true);
    }
  };

  const handleSidebarDragEnd = (_: any, info: PanInfo) => {
    if (info.offset.x < -80 || info.velocity.x < -300) {
      setSidebarOpen(false);
    }
  };

  const handleSuggestionClick = (text: string) => {
    setInput(text);
  };

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-background text-foreground transition-colors duration-300">
      {/* Desktop sidebar */}
      <div className="hidden md:flex">
        <AppSidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={setActiveId}
          onNew={handleNewChat}
          onDelete={handleDelete}
          onRename={handleRename}
          onOpenSearch={() => setSearchOpen(true)}
          collapsed={collapsed}
          onCollapsedChange={setCollapsed}
          theme={theme}
          onThemeChange={setTheme}
        />
      </div>

      {/* Mobile sidebar overlay */}
      <AnimatePresence>
        {sidebarOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
              onClick={() => setSidebarOpen(false)}
            />
            <motion.div
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ duration: 0.35, ease: [0.32, 0.72, 0, 1] }}
              className="fixed inset-y-0 left-0 z-50 w-[280px] md:hidden"
              drag="x"
              dragConstraints={{ left: -SIDEBAR_W, right: 0 }}
              dragElastic={0.1}
              onDragEnd={handleSidebarDragEnd}
            >
              <AppSidebar
                conversations={conversations}
                activeId={activeId}
                onSelect={(id) => {
                  setActiveId(id);
                  setSidebarOpen(false);
                }}
                onNew={() => {
                  handleNewChat();
                  setSidebarOpen(false);
                }}
                onDelete={handleDelete}
                onRename={handleRename}
                onOpenSearch={() => {
                  setSearchOpen(true);
                  setSidebarOpen(false);
                }}
                theme={theme}
                onThemeChange={setTheme}
                mobile
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {!sidebarOpen && isMobile && (
        <motion.div
          className="fixed inset-y-0 left-0 z-30 w-5 md:hidden"
          onPan={handleSwipeDrag}
        />
      )}

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden md:p-2 md:pl-0">
        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden border-0 bg-card text-card-foreground md:rounded-2xl md:border md:border-border md:shadow-sm">
          {/* Mobile menu */}
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label="Open sidebar menu"
            className="fixed left-4 top-4 z-30 flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card/80 shadow-lg backdrop-blur-md transition-all active:scale-95 md:hidden"
          >
            <Menu className="h-5 w-5 text-foreground" />
          </button>

          <div ref={scrollRef} className="flex-1 overflow-y-auto">
            <div className="mx-auto flex min-h-full max-w-2xl flex-col px-4 py-4 md:py-6">
              <AnimatePresence mode="wait">
                {!hasMessages && (
                  <WelcomeScreen
                    visible={!hasMessages}
                    onSuggestionClick={handleSuggestionClick}
                  />
                )}
              </AnimatePresence>

              <AnimatePresence mode="wait">
                <motion.div
                  key={activeId ?? "empty"}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
                >
                  {activeConversation?.messages.map((msg, i) => (
                    <div key={msg.id} className="mb-5 md:mb-6">
                      <ChatMessage
                        message={msg}
                        isLatest={i === activeConversation.messages.length - 1}
                        onRetry={
                          msg.role === "assistant" && msg.error && !loading
                            ? handleRetry
                            : undefined
                        }
                        onThinkLonger={
                          msg.role === "assistant" && !msg.error && !loading
                            ? () => {
                                const userMsg = activeConversation.messages
                                  .slice(
                                    0,
                                    activeConversation.messages.indexOf(msg),
                                  )
                                  .reverse()
                                  .find((m) => m.role === "user");
                                if (userMsg) {
                                  handleThinkLonger(
                                    activeConversation.id,
                                    msg.id,
                                    userMsg.content,
                                  );
                                }
                              }
                            : undefined
                        }
                        isLoading={loading}
                      />
                    </div>
                  ))}
                </motion.div>
              </AnimatePresence>

              {loading &&
                !activeConversation?.messages.some(
                  (m) => m.role === "assistant" && (m.content || m.status),
                ) && (
                  <div className="mb-5 md:mb-6">
                    <LoadingBreadcrumb text="Thinking" />
                  </div>
                )}
            </div>
          </div>

          <div className="shrink-0 px-3 pb-3 pt-2 md:px-4 md:pb-4">
            <div className="mx-auto max-w-2xl space-y-2">
              <ErrorBanner
                message={errorMsg}
                onRetry={hasMessages && !loading ? handleRetry : undefined}
                onDismiss={() => setErrorMsg(null)}
                retrying={retrying}
              />
              <ChatInput
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onSubmit={handleSubmit}
                loading={loading}
                onStop={handleStop}
              >
                <ChatInputTextArea
                  placeholder={
                    serviceAvailable
                      ? "Ask anything about PESU..."
                      : "Service unavailable..."
                  }
                  disabled={!serviceAvailable}
                />
                <ChatInputSubmit />
              </ChatInput>

              <div className="text-center text-xs text-muted-foreground px-3 py-2">
                I am a bot, and I can make mistakes. Please double-check
                responses.
              </div>
            </div>
          </div>
        </div>
      </main>

      <CommandSearch
        conversations={conversations}
        open={searchOpen}
        onOpenChange={setSearchOpen}
        onSelect={(id) => {
          setActiveId(id);
          setSearchOpen(false);
        }}
      />
    </div>
  );
}
