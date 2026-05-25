import { useState } from "react";
import { Copy, Check, Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface MessageActionsProps {
  content: string;
}

export function MessageActions({ content }: MessageActionsProps) {
  const [copied, setCopied] = useState(false);
  const [thinking, setThinking] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleThinkLonger = () => {
    setThinking(true);
    setTimeout(() => setThinking(false), 3000);
  };

  const actions = [
    {
      icon: copied ? Check : Copy,
      label: copied ? "Copied" : "Copy",
      onClick: handleCopy,
      active: copied,
    },
    {
      icon: Brain,
      label: thinking ? "Thinking..." : "Think longer",
      onClick: handleThinkLonger,
      active: thinking,
    },
  ];

  return (
    <div className="flex items-center gap-1 mt-2">
      {actions.map((action) => (
        <Tooltip key={action.label}>
          <TooltipTrigger asChild>
            <button
              onClick={action.onClick}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-all",
                action.active && "text-primary"
              )}
            >
              <action.icon className="h-3.5 w-3.5" />
              <span>{action.label}</span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            {action.label}
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
