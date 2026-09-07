// Conversation list sidebar: switch, rename and delete saved conversations.
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Conversation } from "@/lib/chat-store";
import {
  Plus,
  Search,
  Trash2,
  Pencil,
  Check,
  X,
  PanelLeft,
  PanelRight,
  Moon,
  Sun,
  MessageSquare,
} from "lucide-react";
import { SiGithub } from "@icons-pack/react-simple-icons";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { motion } from "framer-motion";

const COLLAPSED_W = 56;
const EXPANDED_W = 260;
const EASE = [0.4, 0, 0.2, 1] as const;
const SIDEBAR_TRANSITION = { duration: 0.4, ease: EASE };

interface AppSidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onOpenSearch: () => void;
  mobile?: boolean;
  collapsed?: boolean;
  onCollapsedChange?: (next: boolean) => void;
  theme?: "light" | "dark";
  onThemeChange?: (next: "light" | "dark") => void;
}

export function AppSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRename,
  onOpenSearch,
  mobile = false,
  collapsed: collapsedProp,
  onCollapsedChange,
  theme: themeProp,
  onThemeChange,
}: AppSidebarProps) {
  const [collapsedLocal, setCollapsedLocal] = useState(false);
  const collapsed = collapsedProp ?? collapsedLocal;
  const setCollapsed = (next: boolean) => {
    if (onCollapsedChange) onCollapsedChange(next);
    else setCollapsedLocal(next);
  };
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [themeLocal, setThemeLocal] = useState<"light" | "dark">(() => {
    if (typeof window !== "undefined") {
      return document.documentElement.classList.contains("dark")
        ? "dark"
        : "light";
    }
    return "dark";
  });
  const theme = themeProp ?? themeLocal;

  const isCollapsed = mobile ? false : collapsed;

  const toggleTheme = () => {
    const next = theme === "light" ? "dark" : "light";
    if (onThemeChange) onThemeChange(next);
    else {
      setThemeLocal(next);
      localStorage.setItem("askpesu-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
    }
  };

  const startRename = (conv: Conversation) => {
    setEditingId(conv.id);
    setEditTitle(conv.title);
  };

  const confirmRename = () => {
    if (editingId && editTitle.trim()) onRename(editingId, editTitle.trim());
    setEditingId(null);
  };

  const grouped = groupConversationsByDate(conversations);

  return (
    <motion.aside
      animate={{
        width: mobile ? 280 : isCollapsed ? COLLAPSED_W : EXPANDED_W,
      }}
      transition={SIDEBAR_TRANSITION}
      className={cn(
        "flex h-full shrink-0 flex-col overflow-hidden bg-background text-foreground",
        mobile && "rounded-none",
      )}
    >
      {/* Header row -- when collapsed the toggle is centered in the
          narrow rail; when expanded the brand sits on the left and the
          toggle on the right. */}
      <div
        className={cn(
          "flex h-14 items-center pt-3 transition-[padding,justify-content] duration-300",
          isCollapsed ? "px-0 justify-center" : "px-2 justify-between",
        )}
      >
        {/* askPESU brand -- only present when expanded */}
        <motion.div
          initial={false}
          animate={{
            width: isCollapsed ? 0 : "auto",
            opacity: isCollapsed ? 0 : 1,
          }}
          transition={SIDEBAR_TRANSITION}
          className="overflow-hidden"
        >
          <div className="flex items-baseline pl-2 whitespace-nowrap">
            <span
              className="text-lg tracking-wide text-foreground"
              style={{ fontFamily: "'Capriola', sans-serif" }}
            >
              ask
            </span>
            <span
              className="text-lg tracking-wide text-primary"
              style={{ fontFamily: "'Capriola', sans-serif" }}
            >
              PESU
            </span>
          </div>
        </motion.div>

        {!mobile && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg opacity-70 hover:opacity-100 hover:bg-muted/50 transition-all"
                onClick={() => setCollapsed(!isCollapsed)}
                aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {isCollapsed ? (
                  <PanelRight className="h-4 w-4" />
                ) : (
                  <PanelLeft className="h-4 w-4" />
                )}
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              {isCollapsed ? "Expand" : "Collapse"}
            </TooltipContent>
          </Tooltip>
        )}
      </div>

      {/* Action buttons */}
      <div className="px-2 pt-3 space-y-1.5">
        <SidebarButton
          collapsed={isCollapsed}
          onClick={onNew}
          tooltip="New Chat"
          icon={<Plus className="h-4 w-4 ml-1" />}
          label="New Chat"
          className="bg-primary text-primary-foreground hover:bg-primary/90"
        />
        <SidebarButton
          collapsed={isCollapsed}
          onClick={onOpenSearch}
          tooltip="Search"
          icon={<Search className="h-4 w-4" />}
          label="Search"
          className="bg-muted/50 hover:bg-muted"
        />
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-hidden px-2 pb-2 pt-3">
        <motion.div
          initial={false}
          animate={{ opacity: isCollapsed ? 0 : 1 }}
          transition={{
            duration: 0.25,
            delay: isCollapsed ? 0 : 0.15,
            ease: EASE,
          }}
          className={cn(
            "h-full overflow-y-auto pr-1",
            isCollapsed && "pointer-events-none",
          )}
        >
          {conversations.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center opacity-50">
              <p className="text-sm">No conversations yet</p>
              <p className="mt-0.5 text-xs opacity-60">
                Start a new chat to begin
              </p>
            </div>
          ) : (
            grouped.map(({ label, items }) => (
              <div key={label} className="mb-2">
                <p className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  {label}
                </p>
                {items.map((conv) => (
                  <div
                    key={conv.id}
                    className={cn(
                      "group flex cursor-pointer items-center rounded-lg px-2.5 py-2 text-sm transition-colors duration-150",
                      activeId === conv.id
                        ? "text-foreground font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                    )}
                    onClick={() => onSelect(conv.id)}
                  >
                    {editingId === conv.id ? (
                      <div
                        className="flex flex-1 items-center gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          title="Conversation Title"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          onKeyDown={(e) =>
                            e.key === "Enter" && confirmRename()
                          }
                          className="flex-1 border-b border-primary bg-transparent text-sm outline-none"
                          autoFocus
                        />
                        <button
                          onClick={confirmRename}
                          className="text-primary p-1"
                          title="Confirm Rename"
                        >
                          <Check className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="opacity-60 p-1"
                          title="Cancel Rename"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ) : (
                      <>
                        <MessageSquare className="mr-2 h-3.5 w-3.5 shrink-0 opacity-40" />
                        <span className="flex-1 truncate">{conv.title}</span>
                        <div className="ml-1 hidden items-center gap-0.5 group-hover:flex">
                          <button
                            title="Rename"
                            onClick={(e) => {
                              e.stopPropagation();
                              startRename(conv);
                            }}
                            className="rounded-md p-1 transition-colors hover:bg-accent"
                          >
                            <Pencil className="h-3 w-3 opacity-60" />
                          </button>
                          <button
                            title="Delete"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDelete(conv.id);
                            }}
                            className="rounded-md p-1 transition-colors hover:bg-destructive/10 hover:text-destructive"
                          >
                            <Trash2 className="h-3 w-3 opacity-60" />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            ))
          )}
        </motion.div>
      </div>

      {/* Footer: combined theme button + GitHub */}
      <div className="px-2 pb-3 pt-1">
        <motion.div
          initial={false}
          animate={{
            gridTemplateColumns: isCollapsed ? "2.25rem 0fr" : "1fr 2.25rem",
          }}
          transition={SIDEBAR_TRANSITION}
          className="grid w-full items-center gap-1"
        >
          {/* Single theme toggle: icon + label, no outline/border */}
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={toggleTheme}
                aria-label="Toggle theme"
                className={cn(
                  "flex h-9 min-w-0 items-center rounded-lg border-0 bg-transparent outline-none transition-colors hover:bg-muted/50 focus:outline-none focus-visible:ring-0",
                  isCollapsed
                    ? "w-9 justify-center px-0"
                    : "w-full justify-start gap-2 px-2",
                )}
              >
                <span className="relative flex h-4 w-4 shrink-0 items-center justify-center">
                  <Sun
                    className={cn(
                      "absolute h-4 w-4 transition-all duration-300",
                      theme === "light"
                        ? "scale-100 rotate-0 opacity-100"
                        : "scale-0 rotate-90 opacity-0",
                    )}
                  />
                  <Moon
                    className={cn(
                      "absolute h-4 w-4 transition-all duration-300",
                      theme === "dark"
                        ? "scale-100 rotate-0 opacity-100"
                        : "-rotate-90 scale-0 opacity-0",
                    )}
                  />
                </span>
                <motion.span
                  initial={false}
                  animate={{
                    opacity: isCollapsed ? 0 : 1,
                    width: isCollapsed ? 0 : "auto",
                  }}
                  transition={{ duration: 0.25, delay: isCollapsed ? 0 : 0.15 }}
                  className="overflow-hidden whitespace-nowrap text-xs capitalize text-muted-foreground"
                >
                  {theme} mode
                </motion.span>
              </button>
            </TooltipTrigger>
            {isCollapsed && (
              <TooltipContent side="right">Toggle theme</TooltipContent>
            )}
          </Tooltip>

          {/* GitHub -- only visible when expanded */}
          <motion.div
            initial={false}
            animate={{ opacity: isCollapsed ? 0 : 1 }}
            transition={{ duration: 0.25, delay: isCollapsed ? 0 : 0.15 }}
            className="min-w-0 overflow-hidden"
          >
            <a
              href="https://github.com/pesu-dev/ask-pesu"
              target="_blank"
              rel="noopener noreferrer"
              className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-muted/50"
              aria-label="GitHub"
            >
              <SiGithub className="h-3.5 w-3.5 text-muted-foreground" />
            </a>
          </motion.div>
        </motion.div>
      </div>
      {/* Theme toggle at bottom */}
    </motion.aside>
  );
}

/* Shared sidebar button -- icon perfectly centered in collapsed state */
function SidebarButton({
  collapsed,
  icon,
  label,
  onClick,
  tooltip,
  className,
}: {
  collapsed: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  tooltip: string;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          className={cn(
            "w-full overflow-hidden transition-colors rounded-lg",
            className,
          )}
        >
          <motion.div
            initial={false}
            animate={{
              gridTemplateColumns: collapsed ? "2.25rem 0fr" : "2.25rem 1fr",
            }}
            transition={SIDEBAR_TRANSITION}
            className="grid w-full items-center"
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center">
              {icon}
            </span>
            <motion.div
              initial={false}
              animate={{ opacity: collapsed ? 0 : 1 }}
              transition={{
                duration: 0.25,
                delay: collapsed ? 0 : 0.15,
              }}
              className="min-w-0 overflow-hidden"
            >
              <div className="flex min-w-0 items-center pr-3">
                <span className="truncate text-sm font-medium">{label}</span>
              </div>
            </motion.div>
          </motion.div>
        </button>
      </TooltipTrigger>
      {collapsed && <TooltipContent side="right">{tooltip}</TooltipContent>}
    </Tooltip>
  );
}

function groupConversationsByDate(conversations: Conversation[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: { label: string; items: Conversation[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Previous 7 days", items: [] },
    { label: "Older", items: [] },
  ];

  const sorted = [...conversations].sort(
    (a, b) => b.updatedAt.getTime() - a.updatedAt.getTime(),
  );

  sorted.forEach((conv) => {
    const d = conv.updatedAt;
    if (d >= today) groups[0].items.push(conv);
    else if (d >= yesterday) groups[1].items.push(conv);
    else if (d >= weekAgo) groups[2].items.push(conv);
    else groups[3].items.push(conv);
  });

  return groups.filter((g) => g.items.length > 0);
}
