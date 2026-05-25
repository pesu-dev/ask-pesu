import { cn } from "@/lib/utils";

interface LoadingBreadcrumbProps {
  text?: string;
  className?: string;
}

export function LoadingBreadcrumb({ text = "Thinking", className }: LoadingBreadcrumbProps) {
  return (
    <div className={cn("flex items-center gap-3 py-4", className)}>
      <div className="flex items-center gap-1.5" role="status" aria-label="Loading">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="block h-2 w-2 rounded-full bg-primary"
            style={{
              animation: `pulse-dot 1.4s ease-in-out ${i * 0.2}s infinite`,
            }}
          />
        ))}
        <span className="sr-only">Loading</span>
      </div>
      <span className="text-sm font-medium text-muted-foreground">{text}</span>
    </div>
  );
}
