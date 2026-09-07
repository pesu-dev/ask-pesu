// Vendored from shadcn/ui: `cn()` merges Tailwind class strings, resolving
// conflicting utilities so a caller's override actually wins.
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
